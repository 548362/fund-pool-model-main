from __future__ import annotations

import argparse

from src._config import Config
from src.backtest.rolling import run_rolling_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a point-in-time rolling fund backtest")
    parser.add_argument("--start", default=None, help="first eligible date, e.g. 2022-01-01")
    parser.add_argument("--end", default=None, help="last date, e.g. 2026-08-19")
    parser.add_argument("--rebalance", choices=["month", "quarter", "week"], default="month")
    parser.add_argument("--cost-bps", type=float, default=0.0, help="one-way turnover cost in basis points")
    parser.add_argument("--top-n", type=int, default=None)
    parser.add_argument("--weight-scheme", choices=["weight_equal", "weight_risk_parity", "weight_mixed"], default=None)
    parser.add_argument("--max-weight", type=float, default=None, help="single-fund cap, e.g. 0.4")
    args = parser.parse_args()

    config = Config()
    if args.top_n is not None:
        config.top_n_funds = args.top_n
    if args.weight_scheme is not None:
        config.weight_scheme = args.weight_scheme
    if args.max_weight is not None:
        config.max_weight = args.max_weight
    run_rolling_backtest(
        config,
        start_date=args.start,
        end_date=args.end,
        rebalance=args.rebalance,
        cost_bps=args.cost_bps,
    )


if __name__ == "__main__":
    main()
