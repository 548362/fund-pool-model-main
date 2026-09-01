#!/usr/bin/env python3
"""
DB initialization and reset.
"""
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "db" / "fund_db.sqlite"

DDL = [
    """CREATE TABLE IF NOT EXISTS fund_nav_daily(
        fund_code TEXT, date TEXT, nav REAL, acc_nav REAL, daily_return REAL,
        PRIMARY KEY (fund_code, date)
    )""",
    """CREATE TABLE IF NOT EXISTS portfolio_results(
        date TEXT, fund_code TEXT,
        weight_equal REAL, weight_risk_parity REAL, weight_mixed REAL,
        score REAL, rank INTEGER,
        PRIMARY KEY (date, fund_code)
    )""",
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    for sql in DDL:
        conn.execute(sql)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(fund_nav_daily)")}
    if "acc_nav" not in columns:
        conn.execute("ALTER TABLE fund_nav_daily ADD COLUMN acc_nav REAL")
    if "daily_return" not in columns:
        conn.execute("ALTER TABLE fund_nav_daily ADD COLUMN daily_return REAL")
    conn.commit()
    conn.close()
    print(f"DB initialized: {DB_PATH}")


def reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"DB removed: {DB_PATH}")
    init_db()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset_db()
    else:
        init_db()
