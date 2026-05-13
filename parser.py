import pandas as pd
import sqlite3
from pathlib import Path
from database import get_conn, init_db


def parse_and_import(csv_path: str) -> dict:
    """
    Parse a Trade Republic CSV export and insert ETF/stock buy transactions.
    Returns a summary dict with counts.
    """
    df = pd.read_csv(csv_path, parse_dates=["date"])

    # Keep only actual buy trades on investable assets (FUND or STOCK)
    buys = df[
        (df["type"] == "BUY") &
        (df["asset_class"].isin(["FUND", "STOCK"])) &
        (df["symbol"].notna()) &
        (df["shares"].notna()) &
        (df["price"].notna())
    ].copy()

    if buys.empty:
        return {"imported": 0, "skipped": 0}

    # Normalise
    buys["date"] = buys["date"].dt.strftime("%Y-%m-%d")
    buys["amount"] = buys["amount"].abs()  # stored as negative in CSV
    buys["shares"] = buys["shares"].astype(float)
    buys["price"] = buys["price"].astype(float)
    buys["currency"] = buys["currency"].fillna("EUR")

    rows = buys[[
        "transaction_id", "date", "account_type", "asset_class",
        "type", "symbol", "name", "shares", "price", "amount", "currency"
    ]].rename(columns={"symbol": "isin", "transaction_id": "id"})

    imported = 0
    skipped = 0
    errors: list[str] = []
    by_isin: dict[str, dict] = {}

    with get_conn() as conn:
        for _, row in rows.iterrows():
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO transactions
                        (id, date, account_type, asset_class, type, isin,
                         name, shares, price, amount, currency)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    row["id"], row["date"], row["account_type"],
                    row["asset_class"], row["type"], row["isin"],
                    row["name"], row["shares"], row["price"],
                    row["amount"], row["currency"]
                ))
                if conn.execute("SELECT changes()").fetchone()[0] > 0:
                    imported += 1
                    isin = row["isin"]
                    if isin not in by_isin:
                        by_isin[isin] = {"name": row["name"], "asset_class": row["asset_class"], "count": 0}
                    by_isin[isin]["count"] += 1
                else:
                    skipped += 1
            except Exception as e:
                msg = f"[PARSER] Erreur ligne {row['id']}: {e}"
                print(msg)
                errors.append(msg)
                skipped += 1

    print(f"[PARSER] {imported} importées, {skipped} doublons ignorés")
    return {
        "imported": imported,
        "skipped": skipped,
        "by_isin": sorted(by_isin.items(), key=lambda x: -x[1]["count"]),
        "errors": errors[:10],
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python parser.py <path_to_csv>")
        sys.exit(1)
    init_db()
    result = parse_and_import(sys.argv[1])
    print(result)
