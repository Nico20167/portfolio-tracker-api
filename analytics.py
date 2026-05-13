"""
Analytics — computes all portfolio metrics from the local DB.
All functions return plain dicts/lists (JSON-serialisable).
"""

import json
import time as _time
from datetime import date, datetime, timedelta
from database import get_conn

# ── Top companies by (index_name, category) ──────────────────────────────────
# Approximate, based on index factsheets 2024-2025.
# Keys: (index_name matching enricher._INDEX_GEO, country or sector name)
_TOP_COMPANIES: dict[tuple[str, str], list[str]] = {
    # STOXX Europe 600 — by country
    ("STOXX Europe 600", "United Kingdom"): ["AstraZeneca", "Shell", "HSBC", "Unilever", "BP", "GSK", "Rio Tinto"],
    ("STOXX Europe 600", "France"):         ["LVMH", "TotalEnergies", "Hermès", "Sanofi", "L'Oréal", "Airbus", "Schneider Electric"],
    ("STOXX Europe 600", "Switzerland"):    ["Nestlé", "Novartis", "Roche", "UBS", "ABB", "Zurich Insurance", "Richemont"],
    ("STOXX Europe 600", "Germany"):        ["SAP", "Siemens", "Allianz", "Deutsche Telekom", "Infineon", "BMW", "BASF"],
    ("STOXX Europe 600", "Sweden"):         ["Atlas Copco", "Volvo Group", "Ericsson", "Sandvik", "Hexagon", "Alfa Laval"],
    ("STOXX Europe 600", "Netherlands"):    ["ASML", "ING", "Heineken", "Stellantis", "Philips", "NN Group"],
    ("STOXX Europe 600", "Denmark"):        ["Novo Nordisk", "A.P. Møller-Mærsk", "Ørsted", "DSV", "Vestas", "Coloplast", "Pandora"],
    ("STOXX Europe 600", "Spain"):          ["Inditex (Zara)", "Iberdrola", "BBVA", "Santander", "Ferrovial", "Aena"],
    ("STOXX Europe 600", "Italy"):          ["Enel", "ENI", "Ferrari", "Intesa Sanpaolo", "UniCredit", "Leonardo"],
    ("STOXX Europe 600", "Finland"):        ["Nokia", "Kone", "Nordea", "Neste", "Wärtsilä"],
    ("STOXX Europe 600", "Belgium"):        ["Anheuser-Busch InBev", "UCB", "Solvay", "Sofina"],
    ("STOXX Europe 600", "Norway"):         ["Equinor", "Telenor", "DNB", "Yara International"],
    # STOXX Europe 600 — by sector
    ("STOXX Europe 600", "Financials"):            ["HSBC", "BNP Paribas", "Allianz", "AXA", "ING", "Santander"],
    ("STOXX Europe 600", "Health Care"):           ["Novo Nordisk", "AstraZeneca", "Novartis", "Roche", "Sanofi", "GSK"],
    ("STOXX Europe 600", "Industrials"):           ["Airbus", "Siemens", "ABB", "Schneider Electric", "Atlas Copco", "Safran"],
    ("STOXX Europe 600", "Information Technology"): ["SAP", "ASML", "Infineon", "STMicroelectronics", "Capgemini", "Ericsson"],
    ("STOXX Europe 600", "Consumer Discretionary"): ["LVMH", "Hermès", "Ferrari", "BMW", "Stellantis", "Inditex"],
    ("STOXX Europe 600", "Consumer Staples"):      ["Nestlé", "L'Oréal", "Unilever", "Heineken", "Diageo", "Danone"],
    ("STOXX Europe 600", "Energy"):                ["Shell", "TotalEnergies", "BP", "Equinor", "ENI", "Repsol"],
    ("STOXX Europe 600", "Materials"):             ["BASF", "Rio Tinto", "Air Liquide", "Solvay", "Linde"],
    ("STOXX Europe 600", "Communication Services"): ["Deutsche Telekom", "Vodafone", "Orange", "BT Group", "Vivendi"],
    ("STOXX Europe 600", "Utilities"):             ["Iberdrola", "Enel", "National Grid", "E.ON", "Ørsted"],
    ("STOXX Europe 600", "Real Estate"):           ["Vonovia", "Unibail-Rodamco", "Klepierre", "Aroundtown"],

    # MSCI World — by country
    ("MSCI World", "United States"):  ["Apple", "Microsoft", "NVIDIA", "Amazon", "Alphabet (Google)", "Meta", "Tesla"],
    ("MSCI World", "Japan"):          ["Toyota", "Sony", "Keyence", "Mitsubishi UFJ", "SoftBank", "Nintendo", "Hitachi"],
    ("MSCI World", "United Kingdom"): ["AstraZeneca", "Shell", "HSBC", "Unilever", "BP", "GSK"],
    ("MSCI World", "France"):         ["LVMH", "TotalEnergies", "Hermès", "Sanofi", "L'Oréal", "Airbus"],
    ("MSCI World", "Canada"):         ["Royal Bank of Canada", "Shopify", "TD Bank", "Brookfield", "Enbridge"],
    ("MSCI World", "Switzerland"):    ["Nestlé", "Novartis", "Roche", "UBS", "ABB", "Richemont"],
    ("MSCI World", "Germany"):        ["SAP", "Siemens", "Allianz", "Deutsche Telekom", "BASF"],
    ("MSCI World", "Australia"):      ["BHP", "Commonwealth Bank", "CSL", "Macquarie", "ANZ"],
    ("MSCI World", "Netherlands"):    ["ASML", "ING", "Stellantis", "Heineken"],
    ("MSCI World", "Sweden"):         ["Atlas Copco", "Volvo Group", "Ericsson", "Sandvik", "Hexagon"],
    ("MSCI World", "Denmark"):        ["Novo Nordisk", "A.P. Møller-Mærsk", "Ørsted"],
    ("MSCI World", "Hong Kong"):      ["AIA Group", "Jardine Matheson", "HKEX", "CLP Holdings"],
    # MSCI World — by sector
    ("MSCI World", "Information Technology"):  ["Apple", "Microsoft", "NVIDIA", "TSMC", "Broadcom", "ASML"],
    ("MSCI World", "Financials"):              ["JPMorgan Chase", "Visa", "Mastercard", "Bank of America", "HSBC"],
    ("MSCI World", "Health Care"):             ["Eli Lilly", "UnitedHealth", "Johnson & Johnson", "Novo Nordisk", "AstraZeneca"],
    ("MSCI World", "Consumer Discretionary"):  ["Amazon", "Tesla", "LVMH", "Toyota", "Nike", "Mercedes-Benz"],
    ("MSCI World", "Industrials"):             ["Airbus", "Siemens", "Caterpillar", "Honeywell", "ABB", "Atlas Copco"],
    ("MSCI World", "Communication Services"):  ["Alphabet (Google)", "Meta", "Netflix", "Walt Disney", "T-Mobile"],
    ("MSCI World", "Consumer Staples"):        ["Nestlé", "Procter & Gamble", "Coca-Cola", "PepsiCo", "Unilever"],
    ("MSCI World", "Energy"):                  ["ExxonMobil", "Chevron", "Shell", "TotalEnergies", "BP"],
    ("MSCI World", "Materials"):               ["BASF", "Rio Tinto", "BHP", "Linde", "Air Liquide"],
    ("MSCI World", "Utilities"):               ["NextEra Energy", "Duke Energy", "National Grid", "Iberdrola"],
    ("MSCI World", "Real Estate"):             ["Prologis", "American Tower", "Equinix", "Public Storage"],

    # MSCI Emerging Markets — by country
    ("MSCI Emerging Markets", "China"):       ["Tencent", "Alibaba", "Meituan", "JD.com", "PDD Holdings", "CNOOC"],
    ("MSCI Emerging Markets", "India"):       ["Reliance Industries", "HDFC Bank", "Infosys", "TCS", "ICICI Bank"],
    ("MSCI Emerging Markets", "Taiwan"):      ["TSMC", "Hon Hai Precision (Foxconn)", "MediaTek", "Delta Electronics"],
    ("MSCI Emerging Markets", "South Korea"): ["Samsung Electronics", "SK Hynix", "LG Energy Solution", "Hyundai", "Kakao"],
    ("MSCI Emerging Markets", "Brazil"):      ["Petrobras", "Vale", "Itaú Unibanco", "Bradesco", "WEG"],
    ("MSCI Emerging Markets", "Saudi Arabia"): ["Saudi Aramco", "Al Rajhi Bank", "STC", "SABIC"],
    ("MSCI Emerging Markets", "South Africa"): ["Naspers", "FirstRand", "Standard Bank", "Anglo American"],
    ("MSCI Emerging Markets", "Mexico"):      ["América Móvil", "Grupo Bimbo", "Cemex", "Femsa"],
    # MSCI Emerging Markets — by sector
    ("MSCI Emerging Markets", "Financials"):             ["HDFC Bank", "ICICI Bank", "Al Rajhi Bank", "Itaú Unibanco", "Samsung Fire"],
    ("MSCI Emerging Markets", "Information Technology"): ["TSMC", "Samsung Electronics", "Tencent", "Infosys", "SK Hynix"],
    ("MSCI Emerging Markets", "Consumer Discretionary"): ["Alibaba", "JD.com", "Meituan", "PDD Holdings", "Hyundai"],
    ("MSCI Emerging Markets", "Communication Services"): ["Tencent", "Baidu", "NetEase", "Kakao", "América Móvil"],
    ("MSCI Emerging Markets", "Materials"):              ["Vale", "POSCO", "Glencore", "Anglo American Platinum"],
    ("MSCI Emerging Markets", "Energy"):                 ["Petrobras", "Saudi Aramco", "CNOOC", "PTT", "Gazprom"],

    # HSCEI China — by sector (H-shares listed in HK)
    ("HSCEI China", "Financials"):             ["ICBC", "CCB", "Bank of China", "Ping An Insurance", "China Life", "AIA Group"],
    ("HSCEI China", "Consumer Discretionary"): ["Alibaba (HK)", "JD.com (HK)", "Meituan", "Li Ning", "Sands China"],
    ("HSCEI China", "Information Technology"): ["Tencent", "Baidu", "NetEase", "Lenovo", "Xiaomi"],
    ("HSCEI China", "Real Estate"):            ["China Vanke", "Longfor Group", "CIFI Holdings"],
    ("HSCEI China", "Industrials"):            ["CRRC", "China Railway Construction", "Zoomlion"],
    ("HSCEI China", "Energy"):                 ["CNOOC", "China Petroleum (CNOOC)", "China Shenhua Energy"],
    ("HSCEI China", "Health Care"):            ["Sino Biopharmaceutical", "CSPC Pharmaceutical", "BeiGene"],

    # MSCI India — by sector
    ("MSCI India", "Financials"):              ["HDFC Bank", "ICICI Bank", "State Bank of India", "Axis Bank", "Kotak Mahindra"],
    ("MSCI India", "Information Technology"):  ["TCS", "Infosys", "Wipro", "HCL Technologies", "Tech Mahindra"],
    ("MSCI India", "Consumer Discretionary"):  ["Titan Company", "Tata Motors", "Maruti Suzuki", "Asian Paints"],
    ("MSCI India", "Materials"):               ["JSW Steel", "Tata Steel", "Hindalco", "Grasim Industries"],
    ("MSCI India", "Industrials"):             ["Larsen & Toubro", "Adani Ports", "Bharat Electronics"],
    ("MSCI India", "Energy"):                  ["Reliance Industries", "ONGC", "Coal India", "BPCL"],
    ("MSCI India", "Health Care"):             ["Sun Pharmaceutical", "Dr. Reddy's", "Cipla", "Apollo Hospitals"],
    ("MSCI India", "Consumer Staples"):        ["Hindustan Unilever", "ITC", "Nestlé India", "Dabur India"],
    ("MSCI India", "Communication Services"):  ["Bharti Airtel", "Jio Platforms", "Indus Towers"],

    # Bloomberg Europe Defense — by country
    ("Bloomberg Europe Defense", "United Kingdom"): ["BAE Systems", "Rolls-Royce", "QinetiQ", "Chemring"],
    ("Bloomberg Europe Defense", "France"):         ["Thales", "Safran", "Dassault Aviation", "Airbus"],
    ("Bloomberg Europe Defense", "Germany"):        ["Rheinmetall", "Hensoldt", "MTU Aero Engines", "Diehl"],
    ("Bloomberg Europe Defense", "Italy"):          ["Leonardo", "Fincantieri"],
    ("Bloomberg Europe Defense", "Sweden"):         ["Saab AB"],
    ("Bloomberg Europe Defense", "Spain"):          ["Indra", "Navantia"],
    ("Bloomberg Europe Defense", "Norway"):         ["Kongsberg Gruppen", "Nammo"],
    ("Bloomberg Europe Defense", "Netherlands"):    ["Fokker / GKN Aerospace"],
    # Bloomberg Europe Defense — by sector
    ("Bloomberg Europe Defense", "Industrials"):           ["Airbus", "BAE Systems", "Thales", "Rheinmetall", "Safran", "Saab"],
    ("Bloomberg Europe Defense", "Information Technology"): ["Leonardo", "Thales", "Indra", "Hensoldt"],
    ("Bloomberg Europe Defense", "Materials"):              ["Nammo", "Chemring"],
    ("Bloomberg Europe Defense", "Energy"):                 ["Rolls-Royce (nuclear div.)"],
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _latest_price(conn, isin: str) -> float | None:
    row = conn.execute(
        "SELECT close FROM prices WHERE isin = ? ORDER BY date DESC LIMIT 1",
        (isin,)
    ).fetchone()
    return row["close"] if row else None


def _etf_meta(conn, isin: str) -> dict:
    row = conn.execute(
        "SELECT * FROM etf_metadata WHERE isin = ?", (isin,)
    ).fetchone()
    if not row:
        return {}
    return dict(row)


# ─── positions ────────────────────────────────────────────────────────────────

def get_positions() -> list[dict]:
    """
    Returns current positions: one row per ISIN with total shares,
    avg cost, current price, current value, absolute and % gain.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                isin,
                name,
                asset_class,
                account_type,
                SUM(shares)  AS total_shares,
                SUM(amount)  AS total_invested,
                COUNT(*)     AS nb_orders
            FROM transactions
            WHERE type = 'BUY'
            GROUP BY isin
            ORDER BY total_invested DESC
        """).fetchall()

        positions = []
        for r in rows:
            isin = r["isin"]
            price = _latest_price(conn, isin)
            avg_cost = r["total_invested"] / r["total_shares"] if r["total_shares"] else 0
            current_value = (price * r["total_shares"]) if price else None
            gain_abs = (current_value - r["total_invested"]) if current_value else None
            gain_pct = (gain_abs / r["total_invested"] * 100) if (gain_abs is not None and r["total_invested"]) else None

            positions.append({
                "isin": isin,
                "name": r["name"],
                "asset_class": r["asset_class"],
                "account_type": r["account_type"],
                "shares": round(r["total_shares"], 6),
                "avg_cost": round(avg_cost, 4),
                "total_invested": round(r["total_invested"], 2),
                "current_price": round(price, 4) if price else None,
                "current_value": round(current_value, 2) if current_value else None,
                "gain_abs": round(gain_abs, 2) if gain_abs is not None else None,
                "gain_pct": round(gain_pct, 2) if gain_pct is not None else None,
                "nb_orders": r["nb_orders"],
            })

    return positions


# ─── summary KPIs ─────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """
    Top-level KPIs: total invested, current value, total gain, YTD gain,
    monthly breakdown of investments.
    """
    positions = get_positions()

    total_invested = sum(p["total_invested"] for p in positions)
    total_value = sum(p["current_value"] for p in positions if p["current_value"])
    total_gain_abs = total_value - total_invested if total_value else None
    total_gain_pct = (total_gain_abs / total_invested * 100) if (total_gain_abs and total_invested) else None

    # YTD: invested this calendar year
    current_year = date.today().year
    with get_conn() as conn:
        ytd_row = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) AS ytd
            FROM transactions
            WHERE type = 'BUY'
              AND strftime('%Y', date) = ?
        """, (str(current_year),)).fetchone()
        ytd_invested = round(ytd_row["ytd"], 2)

        # Monthly invested (last 12 months)
        monthly_rows = conn.execute("""
            SELECT
                strftime('%Y-%m', date) AS month,
                SUM(amount) AS invested
            FROM transactions
            WHERE type = 'BUY'
              AND date >= date('now', '-12 months')
            GROUP BY month
            ORDER BY month
        """).fetchall()

    monthly = [
        {"month": r["month"], "invested": round(r["invested"], 2)}
        for r in monthly_rows
    ]

    return {
        "total_invested": round(total_invested, 2),
        "total_value": round(total_value, 2) if total_value else None,
        "total_gain_abs": round(total_gain_abs, 2) if total_gain_abs else None,
        "total_gain_pct": round(total_gain_pct, 2) if total_gain_pct else None,
        "ytd_invested": ytd_invested,
        "monthly_investments": monthly,
        "nb_positions": len(positions),
    }


# ─── portfolio evolution ───────────────────────────────────────────────────────

def get_portfolio_evolution() -> list[dict]:
    """
    Daily portfolio value from earliest transaction to today.
    For each date: sum of (shares_held × closing_price) for all positions.
    """
    with get_conn() as conn:
        # All buy transactions ordered by date
        tx_rows = conn.execute("""
            SELECT date, isin, shares, amount
            FROM transactions
            WHERE type = 'BUY'
            ORDER BY date
        """).fetchall()

        if not tx_rows:
            return []

        # All price dates available
        price_rows = conn.execute("""
            SELECT p.date, p.isin, p.close
            FROM prices p
            ORDER BY p.date
        """).fetchall()

    # Build cumulative shares per ISIN
    cumulative: dict[str, float] = {}
    tx_by_date: dict[str, list] = {}
    for r in tx_rows:
        tx_by_date.setdefault(r["date"], []).append(r)

    # Build price lookup: {isin: {date: close}}
    price_lookup: dict[str, dict[str, float]] = {}
    for r in price_rows:
        price_lookup.setdefault(r["isin"], {})[r["date"]] = r["close"]

    # Collect all unique price dates
    all_dates = sorted(set(r["date"] for r in price_rows))

    result = []
    for d in all_dates:
        # Apply any transactions on this date
        for tx in tx_by_date.get(d, []):
            cumulative[tx["isin"]] = cumulative.get(tx["isin"], 0) + tx["shares"]

        # Compute portfolio value: use most recent available price for each isin
        total = 0.0
        has_price = False
        for isin, shares in cumulative.items():
            # Find most recent price ≤ d
            prices_for_isin = price_lookup.get(isin, {})
            available = [dt for dt in prices_for_isin if dt <= d]
            if available:
                price = prices_for_isin[max(available)]
                total += shares * price
                has_price = True

        if has_price and cumulative:
            result.append({"date": d, "value": round(total, 2)})

    return result


# ─── allocation ───────────────────────────────────────────────────────────────

def _weighted_allocation(positions: list[dict], field: str) -> list[dict]:
    """
    Compute portfolio-level weighted allocation for geo or sector.
    field is 'geo_data' or 'sector_data'.
    """
    total_value = sum(
        p["current_value"] for p in positions
        if p["current_value"] and p["asset_class"] == "FUND"
    )
    if not total_value:
        return []

    aggregated: dict[str, float] = {}

    covered_value = 0.0

    with get_conn() as conn:
        for p in positions:
            if p["asset_class"] != "FUND" or not p["current_value"]:
                continue
            meta = _etf_meta(conn, p["isin"])
            raw = meta.get(field)
            if not raw:
                continue
            allocation = json.loads(raw)
            if not allocation:
                continue
            covered_value += p["current_value"]
            weight = p["current_value"] / total_value
            # Detect scale: if max value > 1, data is already 0-100; else 0-1
            scale = 1.0 if max(allocation.values()) > 1 else 100.0

            for category, pct in allocation.items():
                aggregated[category] = aggregated.get(category, 0) + weight * pct * scale

    # Normalize to 100% to account for ETFs without data
    if aggregated and covered_value > 0:
        raw_total = sum(aggregated.values())
        if raw_total > 0:
            aggregated = {k: v * 100 / raw_total for k, v in aggregated.items()}

    result = sorted(
        [{"name": k, "weight": round(v, 2)} for k, v in aggregated.items()],
        key=lambda x: x["weight"],
        reverse=True,
    )
    return result


def get_geo_allocation() -> list[dict]:
    return _weighted_allocation(get_positions(), "geo_data")


def get_sector_allocation() -> list[dict]:
    return _weighted_allocation(get_positions(), "sector_data")


# ─── per-ETF buy transactions ─────────────────────────────────────────────────

# ─── period performance ───────────────────────────────────────────────────────

def get_period_performance(period: str) -> dict:
    """
    Returns portfolio performance for a given period.
    return_abs = end_value - start_value - invested_during   (pure price gain)
    """
    today = date.today()
    today_str = today.isoformat()

    if period == "1m":
        start_str = (today - timedelta(days=30)).isoformat()
        label = "Dernier mois"
    elif period == "mtd":
        start_str = today.replace(day=1).isoformat()
        label = today.strftime("En %B %Y")
    elif period == "ytd":
        start_str = today.replace(month=1, day=1).isoformat()
        label = "Cette année"
    else:
        start_str = None
        label = "Depuis le début"

    with get_conn() as conn:
        all_txs = conn.execute(
            "SELECT date, isin, shares, amount FROM transactions WHERE type='BUY' ORDER BY date"
        ).fetchall()

        if not all_txs:
            return {"period": label, "return_pct": None, "return_abs": None,
                    "start_value": 0, "end_value": 0, "invested_during": 0}

        if start_str is None:
            start_str = all_txs[0]["date"]

        # Shares held at start of period
        shares_start: dict[str, float] = {}
        for tx in all_txs:
            if tx["date"] < start_str:
                shares_start[tx["isin"]] = shares_start.get(tx["isin"], 0) + tx["shares"]

        # All shares held today
        shares_now: dict[str, float] = {}
        for tx in all_txs:
            shares_now[tx["isin"]] = shares_now.get(tx["isin"], 0) + tx["shares"]

        invested_during = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='BUY' AND date >= ?",
            (start_str,)
        ).fetchone()[0]

        def value_at(shares_dict: dict, date_str: str) -> float:
            total = 0.0
            for isin, s in shares_dict.items():
                row = conn.execute(
                    "SELECT close FROM prices WHERE isin=? AND date<=? ORDER BY date DESC LIMIT 1",
                    (isin, date_str)
                ).fetchone()
                if row:
                    total += s * row["close"]
            return total

        start_value = value_at(shares_start, start_str)
        end_value   = value_at(shares_now,   today_str)

    return_abs = end_value - start_value - invested_during
    # When start_value=0 (max period, portfolio didn't exist yet),
    # use total invested as base for a simple ROI metric
    base = start_value if start_value > 0 else invested_during
    return_pct = (return_abs / base * 100) if base > 0 else None

    return {
        "period":          label,
        "start_date":      start_str,
        "start_value":     round(start_value, 2),
        "end_value":       round(end_value, 2),
        "invested_during": round(invested_during, 2),
        "return_abs":      round(return_abs, 2),
        "return_pct":      round(return_pct, 2) if return_pct is not None else None,
    }


# ─── TWRR / MWRR ─────────────────────────────────────────────────────────────

def compute_twrr() -> dict:
    """
    Time-Weighted Rate of Return.
    Splits the investment period into sub-periods at each cash-flow date,
    computes the holding-period return for each, and chains them.
    """
    with get_conn() as conn:
        txs = conn.execute(
            "SELECT date, isin, shares, amount FROM transactions WHERE type='BUY' ORDER BY date"
        ).fetchall()

        if not txs:
            return {"twrr_total": None, "twrr_annualized": None, "years": None}

        from collections import defaultdict
        tx_by_date: dict = defaultdict(list)
        for tx in txs:
            tx_by_date[tx["date"]].append(tx)
        tx_dates = sorted(tx_by_date)
        today_str = date.today().isoformat()

        def value_at(shares_dict: dict, d: str) -> float:
            total = 0.0
            for isin, s in shares_dict.items():
                if s <= 0:
                    continue
                row = conn.execute(
                    "SELECT close FROM prices WHERE isin=? AND date<=? ORDER BY date DESC LIMIT 1",
                    (isin, d)
                ).fetchone()
                if row:
                    total += s * row["close"]
            return total

        shares: dict[str, float] = {}
        sub_returns: list[float] = []
        v_after: float = 0.0

        for d in tx_dates:
            if shares:
                prev_day = (datetime.fromisoformat(d) - timedelta(days=1)).strftime("%Y-%m-%d")
                v_before = value_at(shares, prev_day)
                if v_after > 0:
                    sub_returns.append(v_before / v_after)

            for tx in tx_by_date[d]:
                shares[tx["isin"]] = shares.get(tx["isin"], 0) + tx["shares"]
            v_after = value_at(shares, d)

        # Final sub-period: last buy → today
        if shares and v_after > 0:
            v_today = value_at(shares, today_str)
            sub_returns.append(v_today / v_after)

        if not sub_returns:
            return {"twrr_total": None, "twrr_annualized": None, "years": None}

        factor = 1.0
        for r in sub_returns:
            factor *= r
        twrr_total = factor - 1.0

        first_d = date.fromisoformat(tx_dates[0])
        years = (date.today() - first_d).days / 365.25
        twrr_ann = (factor ** (1 / years) - 1) if years > 0.1 else twrr_total

        return {
            "twrr_total":      round(twrr_total * 100, 2),
            "twrr_annualized": round(twrr_ann    * 100, 2),
            "years":           round(years, 1),
        }


def compute_mwrr() -> dict:
    """
    Money-Weighted Rate of Return = IRR of all cash flows.
    Solved via Newton-Raphson.
    """
    with get_conn() as conn:
        txs = conn.execute(
            "SELECT date, isin, shares, amount FROM transactions WHERE type='BUY' ORDER BY date"
        ).fetchall()

        if not txs:
            return {"mwrr_annualized": None}

        first_d = date.fromisoformat(txs[0]["date"])
        today   = date.today()
        total_days = (today - first_d).days
        if total_days == 0:
            return {"mwrr_annualized": None}

        cash_flows: list[tuple[float, float]] = []
        for tx in txs:
            t = (date.fromisoformat(tx["date"]) - first_d).days / 365.25
            cash_flows.append((t, -tx["amount"]))

        shares: dict[str, float] = {}
        for tx in txs:
            shares[tx["isin"]] = shares.get(tx["isin"], 0) + tx["shares"]

        current_value = 0.0
        for isin, s in shares.items():
            row = conn.execute(
                "SELECT close FROM prices WHERE isin=? ORDER BY date DESC LIMIT 1", (isin,)
            ).fetchone()
            if row:
                current_value += s * row["close"]

        cash_flows.append((total_days / 365.25, current_value))

    def npv(r: float) -> float:
        if r <= -1:
            return float("inf")
        return sum(cf / (1 + r) ** t for t, cf in cash_flows)

    def dnpv(r: float) -> float:
        if r <= -1:
            return float("inf")
        return sum(-t * cf / (1 + r) ** (t + 1) for t, cf in cash_flows)

    r = 0.10
    for _ in range(500):
        n, d = npv(r), dnpv(r)
        if abs(d) < 1e-12:
            break
        r_new = max(-0.99, min(50.0, r - n / d))
        if abs(r_new - r) < 1e-8:
            r = r_new
            break
        r = r_new

    return {"mwrr_annualized": round(r * 100, 2)}


def get_metrics() -> dict:
    twrr = compute_twrr()
    mwrr = compute_mwrr()
    return {
        "twrr_total":      twrr.get("twrr_total"),
        "twrr_annualized": twrr.get("twrr_annualized"),
        "mwrr_annualized": mwrr.get("mwrr_annualized"),
        "years":           twrr.get("years"),
    }


# ─── benchmark comparison ─────────────────────────────────────────────────────

_bench_cache: dict = {}

# iShares Core S&P 500 UCITS ETF — available on JustETF, no API key needed
_SP500_ETF_ISIN = "IE00B5BMR087"


def _fetch_sp500_prices(since: str) -> list[tuple[str, float]]:
    """Fetch S&P 500 proxy prices via justetf_scraping (cached 1h in memory)."""
    global _bench_cache
    now = _time.time()
    if "raw" not in _bench_cache or now - _bench_cache.get("ts", 0) > 3600:
        try:
            import justetf_scraping
            df = justetf_scraping.load_chart(_SP500_ETF_ISIN)
            if df is None or df.empty:
                _bench_cache = {"raw": [], "ts": now}
                return []
            price_col = next(
                (c for c in ["quote", "quote_with_dividends", "close", "Close"] if c in df.columns),
                None
            )
            if price_col is None:
                num_cols = df.select_dtypes(include="number").columns
                price_col = num_cols[0] if len(num_cols) > 0 else None
            if price_col is None:
                _bench_cache = {"raw": [], "ts": now}
                return []
            raw = []
            for idx, row in df.iterrows():
                d = idx if isinstance(idx, str) else idx.strftime("%Y-%m-%d")
                v = float(row[price_col])
                if v > 0:
                    raw.append((d, round(v, 4)))
            _bench_cache = {"raw": raw, "ts": now}
        except Exception as exc:
            print(f"[BENCHMARK] fetch echoue: {exc}")
            _bench_cache = {"raw": [], "ts": now}

    return [(d, v) for d, v in _bench_cache["raw"] if d >= since]


def get_benchmark_comparison(period: str = "max") -> dict:
    """
    Compares portfolio price-only performance (weighted ETF prices, no cash-flow effect)
    against the S&P 500 (iShares Core S&P 500 UCITS ETF), both normalized to base 100.
    """
    days_map = {"1m": 30, "6m": 180, "1y": 365, "2y": 730}
    today = date.today()

    portfolio_evo = get_portfolio_evolution()
    if not portfolio_evo:
        return {"portfolio": [], "benchmark": [], "perf_portfolio": None, "perf_benchmark": None}

    if period in days_map:
        since = (today - timedelta(days=days_map[period])).isoformat()
        portfolio_evo = [d for d in portfolio_evo if d["date"] >= since]

    if not portfolio_evo:
        return {"portfolio": [], "benchmark": [], "perf_portfolio": None, "perf_benchmark": None}

    first_date = portfolio_evo[0]["date"]
    evo_dates  = [d["date"] for d in portfolio_evo]

    # ── Portfolio price-only performance ──────────────────────────────────────
    # Use current position weights × daily price change to remove cash-flow effect.
    positions = get_positions()
    funds = [p for p in positions if p["asset_class"] == "FUND" and p.get("current_value")]
    total_value = sum(p["current_value"] for p in funds)

    norm_portfolio: list[dict] = []

    if total_value > 0:
        with get_conn() as conn:
            # Fetch all prices in bulk per ETF (one query each, not one per date)
            all_prices: dict[str, dict[str, float]] = {}
            for p in funds:
                rows = conn.execute(
                    "SELECT date, close FROM prices WHERE isin=? AND date>=? ORDER BY date",
                    (p["isin"], first_date),
                ).fetchall()
                all_prices[p["isin"]] = {r["date"]: r["close"] for r in rows}

            # Base prices at first_date (forward-fill if no exact match)
            base_prices: dict[str, float] = {}
            for p in funds:
                isin = p["isin"]
                pd_sorted = sorted(all_prices.get(isin, {}))
                candidates = [d for d in pd_sorted if d <= first_date]
                row = conn.execute(
                    "SELECT close FROM prices WHERE isin=? AND date<=? ORDER BY date DESC LIMIT 1",
                    (isin, first_date),
                ).fetchone()
                if row:
                    base_prices[isin] = row["close"]

        # Compute weighted price return for each date
        price_dates = {isin: sorted(prices) for isin, prices in all_prices.items()}

        def price_at(isin: str, d: str) -> float | None:
            dates = price_dates.get(isin, [])
            cands = [x for x in dates if x <= d]
            if not cands:
                return None
            return all_prices[isin][max(cands)]

        for d_str in evo_dates:
            weighted, w_sum = 0.0, 0.0
            for p in funds:
                isin = p["isin"]
                bp = base_prices.get(isin)
                if not bp:
                    continue
                cp = price_at(isin, d_str)
                if cp:
                    w = p["current_value"] / total_value
                    weighted += w * (cp / bp)
                    w_sum += w
            if w_sum > 0:
                norm_portfolio.append({"date": d_str, "value": round(weighted / w_sum * 100, 2)})

    # ── S&P 500 benchmark ─────────────────────────────────────────────────────
    sp500_raw = _fetch_sp500_prices(first_date)
    if not sp500_raw:
        last_p = norm_portfolio[-1]["value"] if norm_portfolio else 100
        return {"portfolio": norm_portfolio, "benchmark": [],
                "perf_portfolio": round(last_p - 100, 2), "perf_benchmark": None}

    sp_lookup = {d: v for d, v in sp500_raw}
    sp_dates  = sorted(sp_lookup)

    def nearest_sp(d_str: str) -> float | None:
        cands = [d for d in sp_dates if d <= d_str]
        return sp_lookup[max(cands)] if cands else None

    base_sp = nearest_sp(first_date)
    if not base_sp:
        last_p = norm_portfolio[-1]["value"] if norm_portfolio else 100
        return {"portfolio": norm_portfolio, "benchmark": [],
                "perf_portfolio": round(last_p - 100, 2), "perf_benchmark": None}

    norm_benchmark = []
    for d in portfolio_evo:
        sv = nearest_sp(d["date"])
        if sv:
            norm_benchmark.append({"date": d["date"], "value": round(sv / base_sp * 100, 2)})

    last_p = norm_portfolio[-1]["value"]  if norm_portfolio  else 100
    last_b = norm_benchmark[-1]["value"] if norm_benchmark else 100

    return {
        "portfolio":      norm_portfolio,
        "benchmark":      norm_benchmark,
        "perf_portfolio": round(last_p - 100, 2),
        "perf_benchmark": round(last_b - 100, 2),
    }


def get_allocation_detail(category_type: str, category_name: str) -> dict:
    """
    For a given country or sector, returns each ETF's contribution
    and the top companies associated with that ETF × category combo.
    """
    from enricher import _resolve_index_name

    positions = get_positions()
    field = "geo_data" if category_type == "geo" else "sector_data"

    funds = [p for p in positions if p["asset_class"] == "FUND" and p["current_value"]]
    total_fund_value = sum(p["current_value"] for p in funds)
    if not total_fund_value:
        return {"category": category_name, "type": category_type, "etfs": []}

    detail_list = []
    with get_conn() as conn:
        for p in funds:
            meta = _etf_meta(conn, p["isin"])
            raw = meta.get(field)
            if not raw:
                continue
            allocation = json.loads(raw)
            if category_name not in allocation:
                continue

            raw_pct = allocation[category_name]
            scale = 1.0 if max(allocation.values()) > 1 else 100.0
            index_pct = raw_pct * scale
            etf_weight = p["current_value"] / total_fund_value
            contribution = index_pct * etf_weight

            index_name = _resolve_index_name(p["isin"], p["name"], None)
            companies = _TOP_COMPANIES.get((index_name, category_name), [])

            detail_list.append({
                "isin": p["isin"],
                "name": p["name"],
                "index_name": index_name or "",
                "index_pct": round(index_pct, 2),
                "etf_weight": round(etf_weight * 100, 2),
                "contribution": round(contribution, 2),
                "companies": companies[:6],
            })

    detail_list.sort(key=lambda x: x["contribution"], reverse=True)
    return {"category": category_name, "type": category_type, "etfs": detail_list}


def get_etf_price_history(isin: str, period: str = "1y") -> list[dict]:
    from datetime import date, timedelta
    days_map = {"3m": 90, "6m": 180, "1y": 365, "2y": 730}
    days = days_map.get(period)
    with get_conn() as conn:
        if days:
            since = (date.today() - timedelta(days=days)).isoformat()
            rows = conn.execute(
                "SELECT date, close FROM prices WHERE isin = ? AND date >= ? ORDER BY date",
                (isin, since),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, close FROM prices WHERE isin = ? ORDER BY date",
                (isin,),
            ).fetchall()
    return [{"date": r["date"], "close": round(r["close"], 4)} for r in rows]


def get_etf_transactions(isin: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date, shares, price, amount
            FROM transactions
            WHERE isin = ? AND type = 'BUY'
            ORDER BY date
        """, (isin,)).fetchall()
    return [
        {
            "date": r["date"],
            "shares": round(r["shares"], 6),
            "price": round(r["price"], 4),
            "amount": round(r["amount"], 2),
        }
        for r in rows
    ]


# ─── per-ETF evolution ────────────────────────────────────────────────────────

def get_etf_evolution(isin: str) -> list[dict]:
    """Daily value for a single ETF position."""
    with get_conn() as conn:
        tx_rows = conn.execute("""
            SELECT date, shares FROM transactions
            WHERE isin = ? AND type = 'BUY'
            ORDER BY date
        """, (isin,)).fetchall()

        price_rows = conn.execute("""
            SELECT date, close FROM prices
            WHERE isin = ?
            ORDER BY date
        """, (isin,)).fetchall()

    if not tx_rows or not price_rows:
        return []

    cumulative_shares = 0.0
    tx_map = {}
    for r in tx_rows:
        tx_map[r["date"]] = tx_map.get(r["date"], 0) + r["shares"]

    price_map = {r["date"]: r["close"] for r in price_rows}
    all_dates = sorted(price_map.keys())

    result = []
    for d in all_dates:
        if d in tx_map:
            cumulative_shares += tx_map[d]
        if cumulative_shares > 0:
            result.append({
                "date": d,
                "value": round(cumulative_shares * price_map[d], 2)
            })

    return result
