#!/usr/bin/env python3
"""Fetch NAV history for a prepared universe without running scoring/backtests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src._config import Config
from src.data.fetcher import Fetcher
from src.data.repository import Repository


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch NAV for a fund universe CSV")
    parser.add_argument("--universe", default="data/universe_v2_pool_seltype_main/universe_fund_candidates.csv")
    parser.add_argument("--db", default="db/fund_db.sqlite")
    parser.add_argument("--since", default="2022-01-01")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    frame = pd.read_csv(args.universe, dtype={"fund_code": str})
    if "fund_code" not in frame.columns:
        raise ValueError("universe CSV must contain fund_code")
    codes = frame["fund_code"].str.extract(r"(\d{6})", expand=False).dropna().drop_duplicates().tolist()
    config = Config(db_path=Path(args.db), since_date=args.since, parallel_workers=args.workers)
    config.validate()
    rows = Fetcher(config, Repository(config)).fetch_and_save_batch(
        codes, since=args.since, max_workers=args.workers
    )
    print(f"funds={len(codes)} rows_written={rows}")


if __name__ == "__main__":
    main()
