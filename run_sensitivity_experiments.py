from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import pandas as pd

from src._config import Config
from src.backtest.rolling import run_rolling_backtest


SCHEMES = ("weight_equal", "weight_mixed", "weight_risk_parity")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run rolling-backtest sensitivity experiments")
    parser.add_argument("--universe", default="data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-08-21")
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--output", default="output/v2_sensitivity")
    args = parser.parse_args()

    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for top_n, scheme, rebalance, max_weight in product(
        (5, 10), SCHEMES, ("month", "quarter"), (1.0, 0.4)
    ):
        cap_label = "uncapped" if max_weight == 1.0 else "cap40"
        experiment = f"top{top_n}_{scheme.removeprefix('weight_')}_{rebalance}_{cap_label}"
        out_dir = root / experiment
        config = Config(
            universe_csv=args.universe,
            universe_limit=50,
            output_dir=out_dir,
            top_n_funds=top_n,
            weight_scheme=scheme,
            max_weight=max_weight,
        )
        run_rolling_backtest(
            config, start_date=args.start, end_date=args.end,
            rebalance=rebalance, cost_bps=args.cost_bps,
        )
        metrics = pd.read_csv(out_dir / "rolling_metrics.csv").set_index("portfolio")
        summary = pd.read_csv(out_dir / "rolling_summary.csv").iloc[0]
        net = metrics.loc["strategy_net"]
        benchmark = metrics.loc["equal_weight_benchmark"]
        rows.append({
            "experiment": experiment,
            "top_n": top_n,
            "weight_scheme": scheme,
            "rebalance": rebalance,
            "max_weight": max_weight,
            "net_total_return": net["total_return"],
            "net_cagr": net["cagr"],
            "net_annual_volatility": net["annual_volatility"],
            "net_sharpe": net["sharpe"],
            "net_max_drawdown": net["max_drawdown"],
            "benchmark_total_return": benchmark["total_return"],
            "benchmark_cagr": benchmark["cagr"],
            "benchmark_sharpe": benchmark["sharpe"],
            "excess_total_return": net["total_return"] - benchmark["total_return"],
            "excess_cagr": net["cagr"] - benchmark["cagr"],
            "annualized_turnover": summary["annualized_turnover"],
            "total_transaction_cost": summary["total_transaction_cost"],
            "beat_benchmark": bool(summary["beat_benchmark"]),
        })
        pd.DataFrame(rows).to_csv(root / "sensitivity_results.csv", index=False)

    results = pd.DataFrame(rows).sort_values(
        ["excess_cagr", "net_sharpe"], ascending=[False, False]
    )
    results.to_csv(root / "sensitivity_results.csv", index=False)
    results.head(10).to_csv(root / "sensitivity_top10.csv", index=False)
    print(results.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
