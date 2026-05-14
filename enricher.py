"""
Enricher — fetches ETF data:
  - geo + sector via JustETF, with fallback on known index compositions
  - price history via justetf_scraping.load_chart(isin)

Synthetic ETFs (swap-based) have no composition on JustETF.
Fallback uses the replicated index composition loaded from etf_compositions.json.
To add or update an ETF/index, edit etf_compositions.json — no Python change needed.
"""

import json
import re
import time
from datetime import date
from pathlib import Path

from database import get_conn


# ── Load compositions from JSON (geo, sectors, isin→index, name patterns) ─────
_DATA_FILE = Path(__file__).parent / "etf_compositions.json"
try:
    with open(_DATA_FILE, encoding="utf-8") as _f:
        _data = json.load(_f)
    _INDEX_GEO: dict[str, dict[str, float]]     = _data["geo"]
    _INDEX_SECTORS: dict[str, dict[str, float]] = _data["sectors"]
    ISIN_TO_INDEX: dict[str, str]               = _data["isin_to_index"]
    _NAME_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(p, re.I), idx) for p, idx in _data["name_patterns"]
    ]
except FileNotFoundError:
    print(f"[ENRICHER] WARN: {_DATA_FILE} introuvable — compositions vides.")
    _INDEX_GEO, _INDEX_SECTORS, ISIN_TO_INDEX, _NAME_PATTERNS = {}, {}, {}, []


def _detect_index(text: str) -> str | None:
    for pattern, index_name in _NAME_PATTERNS:
        if pattern.search(text):
            return index_name
    return None


def _fetch_justetf_overview(isin: str) -> tuple[dict, dict, str | None]:
    """
    Returns (geo_dict, sector_dict, benchmark_hint).
    benchmark_hint is the raw benchmark string from JustETF, may be None.
    """
    try:
        import justetf_scraping
        overview = justetf_scraping.get_etf_overview(isin)
    except ImportError:
        print("[ENRICHER] justetf-scraping non installe.")
        print("  Lance : python -m pip install git+https://github.com/druzsan/justetf-scraping.git")
        return {}, {}, None
    except Exception as e:
        print(f"[ENRICHER] get_etf_overview({isin}) echoue: {e}")
        return {}, {}, None

    geo: dict[str, float] = {}
    for item in overview.get("countries", []):
        name = item.get("name") or item.get("country")
        pct  = item.get("percentage") or item.get("weight", 0)
        if name:
            geo[name] = round(float(pct), 4)

    sectors: dict[str, float] = {}
    for item in overview.get("sectors", []):
        name = item.get("name") or item.get("sector")
        pct  = item.get("percentage") or item.get("weight", 0)
        if name:
            sectors[name] = round(float(pct), 4)

    # Try to grab the replicated index name even when composition is empty
    benchmark: str | None = None
    for key in ("benchmark", "index", "index_name", "replication_index", "fund_index"):
        val = overview.get(key)
        if isinstance(val, str) and val.strip():
            benchmark = val.strip()
            break

    return geo, sectors, benchmark


def _resolve_index_name(isin: str, etf_name: str, benchmark: str | None) -> str | None:
    """
    Resolves which known index this ETF tracks, checking in order:
    1. Explicit ISIN_TO_INDEX mapping
    2. Benchmark string returned by JustETF
    3. ETF name as stored in the database (from Trade Republic CSV)
    """
    if isin in ISIN_TO_INDEX:
        return ISIN_TO_INDEX[isin]

    if benchmark:
        detected = _detect_index(benchmark)
        if detected:
            return detected

    if etf_name:
        detected = _detect_index(etf_name)
        if detected:
            return detected

    return None


def _fetch_allocation(isin: str, etf_name: str) -> tuple[dict, dict]:
    """
    Returns (geo, sectors) using:
    1. JustETF real composition when both geo AND sectors are present (physical ETFs)
    2. Index fallback to fill any missing field (synthetic ETFs or partial JustETF data)
    """
    geo, sectors, benchmark = _fetch_justetf_overview(isin)

    if geo and sectors:
        return geo, sectors

    index_name = _resolve_index_name(isin, etf_name, benchmark)
    if index_name and index_name in _INDEX_GEO:
        fallback_geo = dict(_INDEX_GEO[index_name])
        fallback_sec = dict(_INDEX_SECTORS.get(index_name, {}))
        final_geo     = geo     if geo     else fallback_geo
        final_sectors = sectors if sectors else fallback_sec
        src_geo = "JustETF" if geo     else f"index({index_name})"
        src_sec = "JustETF" if sectors else f"index({index_name})"
        print(f"  Fallback: geo={src_geo}, sec={src_sec}")
        return final_geo, final_sectors

    if geo or sectors:
        return geo, sectors

    if index_name:
        print(f"  WARN: indice '{index_name}' reconnu mais absent des tables de composition")
    else:
        print(f"  WARN: indice non identifie pour {isin} ({etf_name})")
        print(f"        Ajoutez '{isin}': '<nom indice>' dans ISIN_TO_INDEX dans enricher.py")

    return {}, {}


def _fetch_justetf_prices(isin: str, start: str) -> list[tuple[str, float]]:
    """
    Returns [(date_str, close_price), ...] using justetf_scraping.load_chart().
    """
    try:
        import justetf_scraping
        df = justetf_scraping.load_chart(isin)
    except ImportError:
        return []
    except Exception as e:
        print(f"[ENRICHER] load_chart({isin}) echoue: {e}")
        return []

    if df is None or df.empty:
        print(f"[ENRICHER] Aucune donnee de prix pour {isin}")
        return []

    df = df[df.index >= start]

    price_col = None
    for candidate in ["quote", "quote_with_dividends", "close", "Close"]:
        if candidate in df.columns:
            price_col = candidate
            break

    if price_col is None:
        numeric_cols = df.select_dtypes(include="number").columns
        if len(numeric_cols) == 0:
            print(f"[ENRICHER] Aucune colonne numerique dans load_chart pour {isin}")
            print(f"  Colonnes disponibles: {list(df.columns)}")
            return []
        price_col = numeric_cols[0]

    result = []
    for idx, row in df.iterrows():
        date_str = idx if isinstance(idx, str) else idx.strftime("%Y-%m-%d")
        price = row[price_col]
        if price and float(price) > 0:
            result.append((date_str, round(float(price), 4)))

    return result


def _fetch_stooq_prices(ticker: str, start: str) -> list[tuple[str, float]]:
    """
    Fetch historical prices from Stooq (no API key needed).
    ticker format: 'mcd.us' for NYSE, 'aapl.us' for NASDAQ, etc.
    """
    import urllib.request, csv, io
    url = f"https://stooq.com/q/d/l/?s={ticker}&d1={start.replace('-','')}&i=d"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read().decode("utf-8")

        reader = csv.DictReader(io.StringIO(content))
        result = []
        for row in reader:
            date_str = row.get("Date", "").strip()
            close    = row.get("Close", "").strip()
            if date_str and close and close != "null":
                result.append((date_str, round(float(close), 4)))
        return result
    except Exception as e:
        print(f"[ENRICHER] Stooq echoue pour {ticker}: {e}")
        return []


# Individual stocks not on JustETF → Stooq ticker
STOOQ_TICKERS: dict[str, str] = {
    "US5801351017": "mcd.us",  # McDonald's
}


def enrich_all(force: bool = False):
    """
    For each FUND ISIN in transactions:
      1. Geo + sectors via JustETF (or index fallback for synthetic ETFs)
      2. Price history via JustETF load_chart (or Stooq for individual stocks)
    """
    with get_conn() as conn:
        all_rows = conn.execute(
            "SELECT DISTINCT isin, asset_class FROM transactions"
        ).fetchall()

    fund_isins  = [r[0] for r in all_rows if r[1] == "FUND"]
    stock_isins = [r[0] for r in all_rows if r[1] == "STOCK"]

    today = date.today().isoformat()

    # ── ETFs ──────────────────────────────────────────────────────────────────
    for isin in fund_isins:
        print(f"\n[ENRICHER] ETF {isin}...")

        with get_conn() as conn:
            existing = conn.execute(
                "SELECT last_updated FROM etf_metadata WHERE isin = ?", (isin,)
            ).fetchone()
            name_row = conn.execute(
                "SELECT DISTINCT name FROM transactions WHERE isin = ? LIMIT 1", (isin,)
            ).fetchone()
            name = name_row[0] if name_row else isin

        needs_meta = force or existing is None or existing["last_updated"] != today

        if needs_meta:
            geo, sectors = _fetch_allocation(isin, name)
            time.sleep(1.5)

            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO etf_metadata
                        (isin, name, ticker, last_updated, geo_data, sector_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(isin) DO UPDATE SET
                        last_updated = excluded.last_updated,
                        geo_data     = excluded.geo_data,
                        sector_data  = excluded.sector_data
                """, (
                    isin, name, "",
                    today,
                    json.dumps(geo, ensure_ascii=False),
                    json.dumps(sectors, ensure_ascii=False),
                ))

            if geo or sectors:
                print(f"  OK geo: {len(geo)} pays, secteurs: {len(sectors)}")
            else:
                print(f"  WARN aucune donnee geo/secteur")
        else:
            print(f"  meta deja a jour")

        # Prix
        with get_conn() as conn:
            first_date = conn.execute(
                "SELECT MIN(date) FROM transactions WHERE isin = ?", (isin,)
            ).fetchone()[0] or "2024-01-01"
            last_price = conn.execute(
                "SELECT MAX(date) FROM prices WHERE isin = ?", (isin,)
            ).fetchone()[0]

        fetch_from = last_price or first_date
        if fetch_from < today:
            history = _fetch_justetf_prices(isin, fetch_from)
            if history:
                with get_conn() as conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO prices (isin, date, close) VALUES (?,?,?)",
                        [(isin, d, p) for d, p in history]
                    )
                print(f"  OK prix: {len(history)} points (justetf)")
            time.sleep(1.0)

    # ── Individual stocks via Stooq ───────────────────────────────────────────
    for isin in stock_isins:
        ticker = STOOQ_TICKERS.get(isin)
        if not ticker:
            print(f"\n[ENRICHER] STOCK {isin}: pas de ticker Stooq configure, ignore")
            continue

        print(f"\n[ENRICHER] STOCK {isin} ({ticker} via Stooq)...")

        with get_conn() as conn:
            first_date = conn.execute(
                "SELECT MIN(date) FROM transactions WHERE isin = ?", (isin,)
            ).fetchone()[0] or "2024-01-01"
            last_price = conn.execute(
                "SELECT MAX(date) FROM prices WHERE isin = ?", (isin,)
            ).fetchone()[0]

        fetch_from = last_price or first_date
        if fetch_from < today:
            history = _fetch_stooq_prices(ticker, fetch_from)
            if history:
                with get_conn() as conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO prices (isin, date, close) VALUES (?,?,?)",
                        [(isin, d, p) for d, p in history]
                    )
                print(f"  OK prix: {len(history)} points (Stooq)")

    print("\n[ENRICHER] Termine.")


if __name__ == "__main__":
    enrich_all(force=True)
