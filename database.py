import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "portfolio.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (
                id              TEXT PRIMARY KEY,
                date            TEXT NOT NULL,
                account_type    TEXT NOT NULL,
                asset_class     TEXT NOT NULL,
                type            TEXT NOT NULL,
                isin            TEXT NOT NULL,
                name            TEXT NOT NULL,
                shares          REAL NOT NULL,
                price           REAL NOT NULL,
                amount          REAL NOT NULL,
                currency        TEXT NOT NULL DEFAULT 'EUR'
            );

            CREATE TABLE IF NOT EXISTS etf_metadata (
                isin            TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                ticker          TEXT,
                last_updated    TEXT,
                geo_data        TEXT,
                sector_data     TEXT
            );

            CREATE TABLE IF NOT EXISTS prices (
                isin            TEXT NOT NULL,
                date            TEXT NOT NULL,
                close           REAL NOT NULL,
                PRIMARY KEY (isin, date)
            );
        """)
    print(f"[DB] Initialized at {DB_PATH}")
