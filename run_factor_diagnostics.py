from __future__ import annotations

import argparse
from pathlib import Path

from src._config import Config
from src.backtest.factor_diagnostics import run_factor_group_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run point-in-time factor group diagnostics")
    parser.add_argument("--universe", default="data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-08-21")
    parser.add_argument("--rebalance", choices=("month", "quarter"), default="month")
    parser.add_argument("--groups", type=int, default=5)
    parser.add_argument("--output", default="output/v2_factor_diagnostics")
    args = parser.parse_args()

    config = Config(
        universe_csv=args.universe,
        universe_limit=50,
        output_dir=Path(args.output),
    )
    _, _, spreads = run_factor_group_diagnostics(
        config, start_date=args.start, end_date=args.end,
        rebalance=args.rebalance, groups=args.groups,
    )
    print(spreads.to_string(index=False))


if __name__ == "__main__":
    main()
