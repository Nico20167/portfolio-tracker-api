"""
main.py — FastAPI stateless portfolio API.

Each analytics endpoint receives the full portfolio state in the POST body,
builds a temporary in-memory SQLite from it, runs the existing analytics
functions unchanged, then discards the DB. No server-side storage.

Deploy:
  - Backend: Render / Fly.io / Vercel (free tier)
  - Frontend: GitHub Pages (static, points VITE_API to the backend URL)
"""

import io
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
from analytics import (
    get_positions, get_summary, get_portfolio_evolution,
    get_geo_allocation, get_sector_allocation,
    get_etf_evolution, get_etf_price_history, get_etf_transactions,
    get_allocation_detail, get_period_performance,
    get_metrics, get_benchmark_comparison,
)

app = FastAPI(title="Portfolio Tracker — stateless")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent / "frontend"

# Sert le frontend uniquement en local (pas présent sur Render)
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def root():
    if FRONTEND_DIR.exists():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
    return {"status": "ok", "api": "/docs"}


@app.api_route("/api/ping", methods=["GET", "HEAD"])
def ping():
    return {"ok": True}


# ── Portfolio payload model ────────────────────────────────────────────────────

class PortfolioData(BaseModel):
    transactions: list[dict] = []
    prices: dict[str, list[dict]] = {}   # {isin: [{date, close}]}
    metadata: dict[str, dict] = {}       # {isin: {name, geo_data, sector_data}}


# ── In-memory SQLite builder ───────────────────────────────────────────────────

def _build_mem_db(p: PortfolioData) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY, date TEXT, account_type TEXT, asset_class TEXT,
            type TEXT, isin TEXT, name TEXT, shares REAL, price REAL,
            amount REAL, currency TEXT DEFAULT 'EUR'
        );
        CREATE TABLE etf_metadata (
            isin TEXT PRIMARY KEY, name TEXT, ticker TEXT,
            last_updated TEXT, geo_data TEXT, sector_data TEXT
        );
        CREATE TABLE prices (
            isin TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL,
            PRIMARY KEY (isin, date)
        );
    """)
    conn.executemany(
        "INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(t.get("id", ""), t["date"], t.get("account_type", "PEA"),
          t.get("asset_class", "FUND"), t.get("type", "BUY"),
          t["isin"], t["name"], t["shares"], t["price"], t["amount"],
          t.get("currency", "EUR"))
         for t in p.transactions],
    )
    for isin, meta in p.metadata.items():
        conn.execute(
            "INSERT OR REPLACE INTO etf_metadata VALUES (?,?,?,?,?,?)",
            (isin, meta.get("name", isin), "", "2026-01-01",
             json.dumps(meta.get("geo_data", {})),
             json.dumps(meta.get("sector_data", {}))),
        )
    for isin, rows in p.prices.items():
        conn.executemany(
            "INSERT OR REPLACE INTO prices VALUES (?,?,?)",
            [(isin, r["date"], r["close"]) for r in rows],
        )
    return conn


@contextmanager
def _with_portfolio(p: PortfolioData):
    """Build in-memory DB, inject it so analytics functions use it transparently."""
    conn = _build_mem_db(p)
    with database.inject_conn(conn):
        try:
            yield
        finally:
            conn.close()


# ── CSV parse (stateless) ──────────────────────────────────────────────────────

@app.post("/api/parse")
async def parse_csv(file: UploadFile = File(...)):
    """
    Parse a Trade Republic CSV (stateless — nothing stored server-side).
    Handles UTF-8, UTF-8-BOM, UTF-16 and Latin-1 encodings automatically.
    """
    content = await file.read()

    # ── Try multiple encodings ────────────────────────────────────────────────
    df = None
    last_err = ""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(content), encoding=enc)
            break
        except Exception as e:
            last_err = str(e)

    if df is None:
        return {"error": f"Impossible de lire le CSV ({last_err})",
                "transactions": [], "isins": {}}

    cols = list(df.columns)
    print(f"[PARSE] colonnes trouvées: {cols}", flush=True)

    # ── Validate expected columns ─────────────────────────────────────────────
    required = {"type", "asset_class", "symbol", "shares", "price",
                "transaction_id", "name", "amount", "date"}
    missing = required - set(cols)
    if missing:
        return {
            "error": (f"Colonnes manquantes : {sorted(missing)}. "
                      f"Colonnes présentes : {cols}"),
            "transactions": [], "isins": {},
        }

    # ── Filter buys ───────────────────────────────────────────────────────────
    buys = df[
        (df["type"] == "BUY") &
        (df["asset_class"].isin(["FUND", "STOCK"])) &
        (df["symbol"].notna()) &
        (df["shares"].notna()) &
        (df["price"].notna())
    ].copy()

    if buys.empty:
        return {"transactions": [], "isins": {}}

    # ── Normalise ─────────────────────────────────────────────────────────────
    try:
        buys["date"] = pd.to_datetime(buys["date"]).dt.strftime("%Y-%m-%d")
    except Exception as e:
        return {"error": f"Format de date invalide : {e}", "transactions": [], "isins": {}}

    buys["amount"] = buys["amount"].abs()

    transactions, isins = [], {}
    for _, row in buys.iterrows():
        transactions.append({
            "id":           str(row["transaction_id"]),
            "date":         row["date"],
            "account_type": str(row.get("account_type") or "PEA"),
            "asset_class":  row["asset_class"],
            "type":         row["type"],
            "isin":         row["symbol"],
            "name":         row["name"],
            "shares":       float(row["shares"]),
            "price":        float(row["price"]),
            "amount":       float(row["amount"]),
            "currency":     str(row.get("currency") or "EUR"),
        })
        isins[row["symbol"]] = row["name"]

    print(f"[PARSE] {len(transactions)} transactions BUY extraites", flush=True)
    return {"transactions": transactions, "isins": isins}


# ── Per-ISIN enrichment (stateless) ───────────────────────────────────────────

@app.post("/api/enrich-isin")
def enrich_isin(body: dict):
    """
    Enrich a single ISIN: geo/sector data + price history from JustETF.
    body: {isin, name, since}
    """
    import time
    from enricher import (
        _resolve_index_name, _INDEX_GEO, _INDEX_SECTORS, _fetch_justetf_prices,
    )

    isin  = body.get("isin", "")
    name  = body.get("name", isin)
    since = body.get("since", "2020-01-01")

    print(f"\n[ENRICH] >>> {isin} ({name})", flush=True)
    t0 = time.time()

    # ── Geo / sector : fallback direct, sans appel réseau ────────────────────
    # get_etf_overview() hang sur les ETFs synthétiques → on l'ignore.
    # Le fallback par nom/ISIN couvre 100% de nos ETFs PEA.
    idx = _resolve_index_name(isin, name, None)
    if idx and idx in _INDEX_GEO:
        geo     = dict(_INDEX_GEO[idx])
        sectors = dict(_INDEX_SECTORS.get(idx, {}))
        print(f"[ENRICH]   geo/sec: fallback '{idx}' ({len(geo)} pays, {len(sectors)} secteurs)", flush=True)
    else:
        geo, sectors = {}, {}
        print(f"[ENRICH]   geo/sec: indice non reconnu pour '{name}'", flush=True)

    # ── Price history via JustETF ─────────────────────────────────────────────
    t1 = time.time()
    print(f"[ENRICH]   prix: load_chart since {since}...", flush=True)
    try:
        price_rows = _fetch_justetf_prices(isin, since)
        print(f"[ENRICH]   prix: {len(price_rows)} points ({time.time()-t1:.1f}s)", flush=True)
    except Exception as e:
        print(f"[ENRICH]   prix: ERREUR {e}", flush=True)
        price_rows = []

    print(f"[ENRICH] <<< {isin} OK en {time.time()-t0:.1f}s", flush=True)

    return {
        "isin": isin,
        "metadata": {"name": name, "geo_data": geo, "sector_data": sectors},
        "prices":   [{"date": d, "close": c} for d, c in price_rows],
    }


# ── Compute all analytics ──────────────────────────────────────────────────────

@app.post("/api/compute")
def compute(p: PortfolioData):
    """
    Main analytics endpoint. Receives the full portfolio state,
    returns all computed metrics in one call.
    """
    if not p.transactions:
        return {
            "positions": [], "summary": {}, "evolution": [],
            "geo": [], "sectors": [], "metrics": {}, "performance": {},
        }

    with _with_portfolio(p):
        return {
            "positions": get_positions(),
            "summary":   get_summary(),
            "evolution": get_portfolio_evolution(),
            "geo":       get_geo_allocation(),
            "sectors":   get_sector_allocation(),
            "metrics":   get_metrics(),
            "performance": {
                "1m":  get_period_performance("1m"),
                "mtd": get_period_performance("mtd"),
                "ytd": get_period_performance("ytd"),
                "max": get_period_performance("max"),
            },
        }


@app.post("/api/compute/etf")
def compute_etf(p: PortfolioData, isin: str):
    """Per-ETF evolution + transactions (used by ETF detail modal)."""
    with _with_portfolio(p):
        return {
            "evolution":    get_etf_evolution(isin),
            "transactions": get_etf_transactions(isin),
        }


@app.post("/api/compute/price")
def compute_price(p: PortfolioData, isin: str, period: str = "1y"):
    """Price history for an ETF (used by ETF detail chart)."""
    with _with_portfolio(p):
        return get_etf_price_history(isin, period)


@app.post("/api/compute/allocation-detail")
def compute_alloc_detail(p: PortfolioData, type: str, name: str):
    """Allocation breakdown for a country or sector."""
    with _with_portfolio(p):
        return get_allocation_detail(type, name)


@app.post("/api/compute/benchmark")
def compute_benchmark(p: PortfolioData, period: str = "max"):
    """Portfolio vs S&P 500 (iShares proxy) normalized to base 100."""
    with _with_portfolio(p):
        return get_benchmark_comparison(period)


@app.post("/api/compute/performance")
def compute_performance(p: PortfolioData, period: str = "ytd"):
    """Period performance (called when user switches period tab)."""
    with _with_portfolio(p):
        return get_period_performance(period)
