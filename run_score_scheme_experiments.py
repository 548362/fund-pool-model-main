from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src._config import Config
from src.backtest.factor_diagnostics import run_factor_correlation_diagnostics, run_factor_group_diagnostics
from src.backtest.metrics import performance_metrics
from src.backtest.rolling import run_rolling_backtest
from src.backtest.score_schemes import SCORE_SCHEMES, validate_score_schemes


def _metrics_for_curve(curve: pd.DataFrame, start: str, end: str) -> dict[str, float | str]:
    subset = curve[(pd.to_datetime(curve["date"]) >= pd.Timestamp(start)) & (pd.to_datetime(curve["date"]) <= pd.Timestamp(end))]
    if subset.empty:
        return {}
    strategy = performance_metrics(subset["net_return"], dates=subset["date"])
    benchmark = performance_metrics(subset["benchmark_return"], dates=subset["date"])
    return {
        "net_total_return": strategy["total_return"],
        "net_cagr": strategy["cagr"],
        "net_sharpe": strategy["sharpe"],
        "net_max_drawdown": strategy["max_drawdown"],
        "benchmark_total_return": benchmark["total_return"],
        "benchmark_cagr": benchmark["cagr"],
        "benchmark_sharpe": benchmark["sharpe"],
        "excess_total_return": strategy["total_return"] - benchmark["total_return"],
        "excess_cagr": strategy["cagr"] - benchmark["cagr"],
        "beat_benchmark": bool(strategy["total_return"] > benchmark["total_return"]),
    }


def _turnover_for_period(trades: pd.DataFrame, start: str, end: str, curve: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"annualized_turnover": 0.0, "total_transaction_cost": 0.0}
    effective = pd.to_datetime(trades["effective_date"], errors="coerce")
    selected = trades[effective.between(pd.Timestamp(start), pd.Timestamp(end), inclusive="both")]
    period_curve = curve[(pd.to_datetime(curve["date"]) >= pd.Timestamp(start)) & (pd.to_datetime(curve["date"]) <= pd.Timestamp(end))]
    years = max((pd.to_datetime(period_curve["date"]).max() - pd.to_datetime(period_curve["date"]).min()).days / 365.25, 1 / 252)
    return {
        "annualized_turnover": float(selected["turnover"].sum() / years) if not selected.empty else 0.0,
        "total_transaction_cost": float(selected["applied_cost"].sum()) if not selected.empty else 0.0,
    }


def _run_scheme(name: str, weights: dict[str, float], args: argparse.Namespace, root: Path) -> tuple[dict, list[dict]]:
    out_dir = root / name
    config = Config(
        universe_csv=args.universe,
        universe_limit=50,
        top_n_funds=10,
        weight_scheme="weight_equal",
        max_weight=1.0,
        output_dir=out_dir,
        factor_weights=weights,
        since_date=args.start,
    )
    curve = run_rolling_backtest(config, start_date=args.start, end_date=args.end, rebalance="month", cost_bps=10.0)
    trades = pd.read_csv(out_dir / "rolling_trades.csv")
    curve_dates = pd.to_datetime(curve["date"])
    effective_start = max(pd.Timestamp(args.start), curve_dates.min()).strftime("%Y-%m-%d")
    periods = [
        ("full", effective_start, args.end),
        ("early", curve_dates.min().strftime("%Y-%m-%d"), "2024-12-31"),
        ("late", "2025-01-01", args.end),
    ]
    rows = []
    for period, start, end in periods:
        metrics = _metrics_for_curve(curve, start, end)
        if not metrics:
            continue
        metrics.update(_turnover_for_period(trades, start, end, curve))
        rows.append({"scheme": name, "period": period, "start": start, "end": end, **metrics})
    full = next(row for row in rows if row["period"] == "full")
    return full, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare fixed-parameter factor scoring schemes")
    parser.add_argument("--universe", default="data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-08-21")
    parser.add_argument("--output", default="output/v2_factor_optimization")
    args = parser.parse_args()
    universe_path = Path(args.universe)
    if not universe_path.exists():
        fallback = Path("data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv")
        if fallback.exists():
            print(f"[EXPERIMENT] universe not found: {args.universe}; using {fallback}")
            args.universe = str(fallback)
        else:
            raise FileNotFoundError(f"Fund universe not found: {args.universe}")
    validate_score_schemes()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)

    diagnostic_config = Config(
        universe_csv=args.universe,
        universe_limit=50,
        output_dir=root,
        since_date=args.start,
        top_n_funds=10,
        weight_scheme="weight_equal",
    )
    run_factor_correlation_diagnostics(diagnostic_config, start_date=args.start, end_date=args.end, rebalance="month")
    run_factor_group_diagnostics(diagnostic_config, start_date=args.start, end_date=args.end, rebalance="month", groups=5)

    full_rows, period_rows = [], []
    manifest_rows = []
    for name, weights in SCORE_SCHEMES.items():
        full, rows = _run_scheme(name, weights, args, root)
        full_rows.append(full)
        period_rows.extend(rows)
        manifest_rows.append({
            "scheme": name,
            "factor_weights": json.dumps(weights, sort_keys=True),
            "universe": args.universe,
            "top_n": 10,
            "weight_scheme": "weight_equal",
            "rebalance": "month",
            "cost_bps": 10.0,
            "start": args.start,
            "end": args.end,
        })
    pd.DataFrame(full_rows).to_csv(root / "score_scheme_summary.csv", index=False)
    pd.DataFrame(period_rows).to_csv(root / "score_scheme_period_summary.csv", index=False)
    pd.DataFrame(manifest_rows).to_csv(root / "experiment_manifest.csv", index=False)
    print(pd.DataFrame(full_rows).to_string(index=False))


if __name__ == "__main__":
    main()
