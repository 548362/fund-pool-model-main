from __future__ import annotations

import sqlite3

import pandas as pd

from .._config import Config
from .._exceptions import BacktestError
from ..reporting.charts import plot_equity_comparison
from .accounting import simulate_rebalance_weights
from .metrics import performance_table


VALID_WEIGHT_COLUMNS = {
    "weight_equal",
    "weight_risk_parity",
    "weight_mixed",
}


def run_backtest(
    config: Config,
    weight_col: str | None = None,
    *,
    cost_bps: float = 0.0,
) -> pd.DataFrame:
    """Replay historical target weights stored in the portfolio table.

    This mode evaluates decisions that have already been persisted. Use the
    rolling backtest when historical factors and portfolios must be rebuilt at
    each point in time.
    """
    config.validate()
    weight_col = weight_col or config.weight_scheme
    if weight_col not in VALID_WEIGHT_COLUMNS:
        raise ValueError(f"Unknown weight column: {weight_col}")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    if not config.db_path.exists():
        raise BacktestError(f"DB not found: {config.db_path}")

    with sqlite3.connect(config.db_path) as conn:
        weights_long = pd.read_sql(
            f"""
            SELECT date, fund_code, {weight_col} AS weight
            FROM {config.portfolio_table}
            WHERE date >= date(?)
            """,
            conn,
            params=[config.since_date],
            parse_dates=["date"],
        )
        nav = pd.read_sql(
            f"SELECT date, fund_code, nav FROM {config.nav_table}",
            conn,
            parse_dates=["date"],
        )

    if weights_long.empty:
        raise BacktestError(
            f"No weights in {config.portfolio_table} since {config.since_date}"
        )
    if nav.empty:
        raise BacktestError(f"No NAV data in {config.nav_table}")

    weights_long["fund_code"] = weights_long["fund_code"].astype(str).str.zfill(6)
    nav["fund_code"] = nav["fund_code"].astype(str).str.zfill(6)


    rebalance_weights = weights_long.pivot_table(
        index="date",
        columns="fund_code",
        values="weight",
        aggfunc="last",
        fill_value=0.0,
    ).sort_index()

    prices = nav.pivot_table(
        index="date",
        columns="fund_code",
        values="nav",
        aggfunc="last",
    ).sort_index()
    fund_returns = prices.pct_change(fill_method=None)
    benchmark_returns = fund_returns.mean(axis=1, skipna=True)

    curve, trades = simulate_rebalance_weights(
        fund_returns,
        rebalance_weights,
        benchmark_returns=benchmark_returns,
        cost_bps=cost_bps,
    )
    curve.insert(1, "equity", curve["net_equity"])

    out_dir = config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    curve.to_csv(out_dir / "equity_curve.csv", index=False)
    trades.to_csv(out_dir / "backtest_trades.csv", index=False)
    plot_equity_comparison(curve, out_dir / "equity_curve.png")

    metrics = performance_table(
        {
            "strategy_gross": curve["gross_return"],
            "strategy_net": curve["net_return"],
            "equal_weight_benchmark": curve["benchmark_return"],
        },
        dates=curve["date"],
    )
    metrics.to_csv(out_dir / "backtest_metrics.csv", index=False)

    print(f"[BACKTEST] saved: {out_dir / 'equity_curve.csv'}")
    print(f"[BACKTEST] saved: {out_dir / 'backtest_metrics.csv'}")
    print(f"[BACKTEST] saved: {out_dir / 'backtest_trades.csv'}")
    return curve
