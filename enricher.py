"""
Enricher — fetches ETF data:
  - geo + sector via JustETF, with fallback on known index compositions
  - price history via justetf_scraping.load_chart(isin)

Synthetic ETFs (swap-based) have no composition on JustETF.
Fallback uses the replicated index composition (MSCI World, STOXX Europe 600, etc.)
"""

import json
import re
import time
from datetime import date

from database import get_conn


# ── Known index compositions (approximate weights, 2024-2025) ─────────────────
# Sources: MSCI, STOXX, S&P index factsheets

_INDEX_GEO: dict[str, dict[str, float]] = {
    "MSCI World": {
        "United States": 70.2, "Japan": 5.8, "United Kingdom": 4.1,
        "France": 3.1, "Canada": 3.0, "Switzerland": 2.9,
        "Germany": 2.2, "Australia": 1.9, "Netherlands": 1.4,
        "Sweden": 1.0, "Denmark": 0.9, "Hong Kong": 0.8,
        "Spain": 0.7, "Italy": 0.6, "Others": 1.4,
    },
    "MSCI Emerging Markets": {
        "China": 27.1, "India": 18.2, "Taiwan": 17.3,
        "South Korea": 11.8, "Brazil": 5.2, "Saudi Arabia": 4.0,
        "South Africa": 3.1, "Mexico": 2.0, "Indonesia": 1.5,
        "Thailand": 1.3, "Malaysia": 1.2, "Others": 7.3,
    },
    "STOXX Europe 600": {
        "United Kingdom": 23.2, "France": 17.1, "Switzerland": 16.0,
        "Germany": 13.2, "Sweden": 5.9, "Netherlands": 5.4,
        "Denmark": 4.3, "Spain": 3.2, "Italy": 3.0,
        "Finland": 1.5, "Belgium": 1.4, "Norway": 1.3, "Others": 4.5,
    },
    "HSCEI China": {
        "China": 100.0,
    },
    "MSCI India": {
        "India": 100.0,
    },
    "Bloomberg Europe Defense": {
        "United Kingdom": 22.0, "France": 21.0, "Germany": 14.0,
        "Italy": 10.0, "Sweden": 9.0, "Spain": 5.0,
        "Norway": 4.0, "Netherlands": 3.0, "Others": 12.0,
    },
    "S&P 500": {"United States": 100.0},
    "MSCI USA": {"United States": 100.0},
    "NASDAQ-100": {"United States": 96.2, "Others": 3.8},
    "MSCI Europe": {
        "United Kingdom": 25.0, "France": 18.5, "Switzerland": 15.5,
        "Germany": 12.8, "Netherlands": 5.5, "Sweden": 5.5,
        "Denmark": 4.0, "Spain": 3.2, "Italy": 2.8, "Others": 7.2,
    },
    "CAC 40": {"France": 100.0},
    "Russell 2000": {"United States": 100.0},
    "MSCI ACWI": {
        "United States": 62.5, "Japan": 5.2, "United Kingdom": 3.6,
        "China": 2.9, "France": 2.8, "Canada": 2.7, "India": 2.4,
        "Switzerland": 2.6, "Germany": 1.9, "Taiwan": 1.7, "Others": 11.7,
    },
}

_INDEX_SECTORS: dict[str, dict[str, float]] = {
    "MSCI World": {
        "Information Technology": 22.4, "Financials": 16.2,
        "Health Care": 11.8, "Consumer Discretionary": 10.8,
        "Industrials": 10.4, "Communication Services": 8.1,
        "Consumer Staples": 6.9, "Energy": 4.7,
        "Materials": 3.8, "Utilities": 2.7, "Real Estate": 2.2,
    },
    "MSCI Emerging Markets": {
        "Financials": 21.3, "Information Technology": 20.5,
        "Consumer Discretionary": 12.1, "Communication Services": 10.2,
        "Materials": 8.0, "Energy": 6.8, "Industrials": 6.2,
        "Consumer Staples": 4.5, "Health Care": 4.3,
        "Utilities": 3.5, "Real Estate": 2.6,
    },
    "STOXX Europe 600": {
        "Financials": 18.2, "Industrials": 15.1, "Health Care": 13.8,
        "Consumer Discretionary": 10.3, "Consumer Staples": 9.2,
        "Information Technology": 8.5, "Materials": 7.1,
        "Energy": 6.0, "Communication Services": 4.9,
        "Utilities": 4.0, "Real Estate": 2.9,
    },
    "HSCEI China": {
        "Financials": 33.0, "Consumer Discretionary": 20.0,
        "Information Technology": 15.0, "Real Estate": 8.0,
        "Industrials": 8.0, "Energy": 7.0,
        "Health Care": 5.0, "Others": 4.0,
    },
    "MSCI India": {
        "Financials": 25.0, "Information Technology": 22.0,
        "Consumer Discretionary": 10.0, "Materials": 8.0,
        "Industrials": 7.0, "Energy": 7.0, "Health Care": 7.0,
        "Consumer Staples": 5.0, "Communication Services": 4.0,
        "Utilities": 3.0, "Real Estate": 2.0,
    },
    "Bloomberg Europe Defense": {
        "Industrials": 82.0, "Information Technology": 12.0,
        "Materials": 4.0, "Energy": 2.0,
    },
    "S&P 500": {
        "Information Technology": 31.5, "Financials": 13.5,
        "Health Care": 11.5, "Consumer Discretionary": 10.5,
        "Industrials": 8.5, "Communication Services": 8.5,
        "Consumer Staples": 6.0, "Energy": 3.8,
        "Materials": 2.5, "Utilities": 2.5, "Real Estate": 1.2,
    },
    "MSCI USA": {
        "Information Technology": 31.5, "Financials": 13.5,
        "Health Care": 11.5, "Consumer Discretionary": 10.5,
        "Industrials": 8.5, "Communication Services": 8.5,
        "Consumer Staples": 6.0, "Energy": 3.8,
        "Materials": 2.5, "Utilities": 2.5, "Real Estate": 1.2,
    },
    "NASDAQ-100": {
        "Information Technology": 52.0, "Communication Services": 17.0,
        "Consumer Discretionary": 14.0, "Health Care": 6.5,
        "Industrials": 4.5, "Financials": 2.5, "Others": 3.5,
    },
    "MSCI Europe": {
        "Financials": 18.5, "Industrials": 15.8, "Health Care": 15.2,
        "Consumer Staples": 10.5, "Consumer Discretionary": 10.0,
        "Materials": 7.5, "Energy": 6.2, "Information Technology": 6.0,
        "Communication Services": 4.8, "Utilities": 3.5, "Real Estate": 2.0,
    },
    "MSCI ACWI": {
        "Information Technology": 23.5, "Financials": 15.8,
        "Health Care": 11.5, "Consumer Discretionary": 10.5,
        "Industrials": 10.3, "Communication Services": 7.8,
        "Consumer Staples": 6.5, "Energy": 4.5,
        "Materials": 4.0, "Utilities": 2.8, "Real Estate": 2.8,
    },
    "CAC 40": {
        "Consumer Discretionary": 18.0, "Industrials": 17.0,
        "Financials": 13.5, "Materials": 10.5, "Health Care": 10.0,
        "Information Technology": 8.5, "Energy": 7.5,
        "Consumer Staples": 7.0, "Communication Services": 5.0,
        "Utilities": 3.0,
    },
    "Russell 2000": {
        "Financials": 22.0, "Industrials": 18.5, "Health Care": 16.5,
        "Consumer Discretionary": 10.5, "Information Technology": 10.0,
        "Real Estate": 7.5, "Materials": 4.0, "Energy": 3.5,
        "Consumer Staples": 3.5, "Utilities": 2.5, "Communication Services": 1.5,
    },
}


# ── ISIN → index mapping for known PEA synthetic ETFs ────────────────────────
# Fallback de dernier recours si la détection par nom échoue.
# La détection par nom ETF (Trade Republic) couvre déjà la majorité des cas.
ISIN_TO_INDEX: dict[str, str] = {
    "FR0011871078": "HSCEI China",           # PEA HSCEI China EUR (Acc)
    "FR0011869320": "MSCI India",            # PEA MSCI India EUR (Acc)
    "LU3047998896": "Bloomberg Europe Defense",  # Easy Bloomberg Europe Defense EUR
}


# ── Index name detection from ETF name string ─────────────────────────────────
_NAME_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Order matters: more specific patterns first
    (re.compile(r"hscei|hang\s+seng\s+china",    re.I), "HSCEI China"),
    (re.compile(r"msci\s+india\b",               re.I), "MSCI India"),
    (re.compile(r"defense|defence",              re.I), "Bloomberg Europe Defense"),
    (re.compile(r"msci\s+world",                 re.I), "MSCI World"),
    (re.compile(r"msci\s+em|emerging\s+market",  re.I), "MSCI Emerging Markets"),
    (re.compile(r"stoxx\s+europe\s+600",         re.I), "STOXX Europe 600"),
    (re.compile(r"s[&\s]*p\s*500|sp500",         re.I), "S&P 500"),
    (re.compile(r"nasdaq.?100",                  re.I), "NASDAQ-100"),
    (re.compile(r"msci\s+europe\b",              re.I), "MSCI Europe"),
    (re.compile(r"msci\s+usa\b",                 re.I), "MSCI USA"),
    (re.compile(r"cac\s*40",                     re.I), "CAC 40"),
    (re.compile(r"russell\s*2000",               re.I), "Russell 2000"),
    (re.compile(r"msci\s+acwi|all\s+countr",     re.I), "MSCI ACWI"),
]


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
