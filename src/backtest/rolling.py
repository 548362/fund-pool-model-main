from __future__ import annotations

import sqlite3
import hashlib
import json
from pathlib import Path

import pandas as pd

from .._config import Config
from .._exceptions import BacktestError
from ..common.utils import log
from ..data.pool import UniversePool
from ..data.repository import Repository
from ..domain.factors import compute_factors
from ..domain.optimizer import build_portfolio
from ..domain.scoring import score_funds
from ..reporting.charts import plot_equity_comparison
from .accounting import cap_weights, simulate_rebalance_weights
from .metrics import performance_table



def _month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the last available trading date in each calendar month."""
    dates = pd.DatetimeIndex(index).sort_values().unique()
    if len(dates) == 0:
        return dates
    return pd.DatetimeIndex(pd.Series(dates, index=dates).groupby(dates.to_period("M")).last())


def _quarter_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the last available trading date in each calendar quarter."""
    dates = pd.DatetimeIndex(index).sort_values().unique()
    if len(dates) == 0:
        return dates
    return pd.DatetimeIndex(pd.Series(dates, index=dates).groupby(dates.to_period("Q")).last())


def _first_usable_date(index: pd.DatetimeIndex, window: int) -> pd.Timestamp:
    """Return the date on which ``window`` actual return observations exist."""
    dates = pd.DatetimeIndex(index).sort_values().unique()
    if window < 2 or len(dates) < window:
        raise BacktestError(f"Fewer than {window} trading-day observations are available")
    return pd.Timestamp(dates[window - 1])


def run_rolling_backtest(
    config: Config,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    rebalance: str = "month",
    cost_bps: float = 0.0,
) -> pd.DataFrame:
    """Run a signal point-in-time backtest over a fixed configured universe.

    At each rebalance date, factors and scores use only returns through that date.
    The resulting weights are applied from the next trading day until the next
    rebalance date. Results are written to the configured output directory.
    """
    config.validate()
    if rebalance not in {"month", "quarter", "week"}:
        raise ValueError("rebalance must be 'month', 'quarter' or 'week'")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")


    universe = UniversePool(config).load()
    universe_warning = (
        "Signals are point-in-time, but the configured fund universe is fixed and may contain "
        "survivorship/availability bias."
    )
    log(f"[ROLLING] WARNING: {universe_warning}")
    repo = Repository(config)
    nav = repo.load_nav(universe, since=config.since_date)
    if nav.empty:
        raise BacktestError(f"No NAV data in {config.nav_table} for the configured universe")
    nav = nav.dropna(subset=["date", "nav"]).sort_values(["fund_code", "date"])
    if nav.empty:
        raise BacktestError("No NAV data remains after applying the fund universe")

    returns = repo.to_returns(nav)
    if returns.empty:
        raise BacktestError("Unable to calculate fund returns")
    returns["date"] = pd.to_datetime(returns["date"])
    returns = returns.sort_values("date")
    dates = pd.DatetimeIndex(sorted(returns["date"].unique()))

    start = pd.Timestamp(start_date or config.since_date)
    end = pd.Timestamp(end_date) if end_date else dates.max()
    dates = dates[(dates >= start) & (dates <= end)]
    if len(dates) < 2:
        raise BacktestError("The selected backtest range has fewer than two trading days")

    ret_wide = returns.pivot_table(index="date", columns="fund_code", values="ret", aggfunc="last").sort_index()
    benchmark = returns.groupby("date")["ret"].mean().sort_index()
    if rebalance == "month":
        rebalance_dates = _month_end_dates(dates)
    elif rebalance == "quarter":
        rebalance_dates = _quarter_end_dates(dates)
    else:
        rebalance_dates = pd.DatetimeIndex(pd.Series(dates, index=dates).groupby(dates.to_period("W")).last())
    rebalance_dates = rebalance_dates[(rebalance_dates >= dates.min()) & (rebalance_dates <= dates.max())]


    first_usable = _first_usable_date(dates, config.window_days)
    rebalance_dates = rebalance_dates[rebalance_dates >= first_usable]
    if len(rebalance_dates) == 0:
        raise BacktestError("No rebalance date has enough history for the configured factor window")

    weight_rows: list[pd.Series] = []
    holding_rows: list[pd.DataFrame] = []

    for rebalance_date in rebalance_dates:
        hist = returns[returns["date"] <= rebalance_date]
        factors = compute_factors(
            hist,
            bench=benchmark[benchmark.index <= rebalance_date],
            window=config.window_days,
        )
        scores = score_funds(
            factors,
            factor_weights=config.factor_weights,
            pure_sharpe_only=config.pure_sharpe_only,
        )
        portfolio = build_portfolio(
            scores,
            hist,
            rebalance_date.strftime("%Y-%m-%d"),
            top_n=config.top_n_funds,
            window_days=config.window_days,
        )
        if portfolio.empty:
            log(f"[ROLLING] skip {rebalance_date.date()}: no eligible portfolio")
            continue

        weight_col = config.weight_scheme
        if weight_col not in portfolio.columns:
            raise BacktestError(f"Unknown portfolio weight column: {weight_col}")
        weights = portfolio.set_index("fund_code")[weight_col].astype(float)
        weights = weights / (weights.abs().sum() or 1.0)
        if config.max_weight < 1.0:
            weights = cap_weights(weights, config.max_weight)
        weights.name = rebalance_date
        weight_rows.append(weights)
        holding_rows.append(portfolio.assign(rebalance_date=rebalance_date.date()))

    if not weight_rows:
        raise BacktestError("No target weights were produced by the rolling backtest")

    target_weights = pd.DataFrame(weight_rows).fillna(0.0).sort_index()
    benchmark_returns = ret_wide.mean(axis=1, skipna=True)
    curve, trades = simulate_rebalance_weights(
        ret_wide.reindex(dates),
        target_weights,
        benchmark_returns=benchmark_returns,
        cost_bps=cost_bps,
    )
    if curve.empty:
        raise BacktestError("No daily returns were produced by the rolling backtest")

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    holdings = pd.concat(holding_rows, ignore_index=True) if holding_rows else pd.DataFrame()
    fund_counts = (target_weights != 0.0).sum(axis=1)
    trades["fund_count"] = pd.to_datetime(trades["date"]).map(fund_counts)
    curve.to_csv(out_dir / "rolling_equity_curve.csv", index=False)
    plot_equity_comparison(curve, out_dir / "rolling_equity_curve.png")
    holdings.to_csv(out_dir / "rolling_holdings.csv", index=False)
    trades.to_csv(out_dir / "rolling_trades.csv", index=False)

    metrics = performance_table(
        {
            "strategy_gross": curve["gross_return"],
            "strategy_net": curve["net_return"],
            "equal_weight_benchmark": curve["benchmark_return"],
        },
        dates=curve["date"],
    )
    metrics.to_csv(out_dir / "rolling_metrics.csv", index=False)

    metric_by_name = metrics.set_index("portfolio")
    executed_trades = trades[trades["effective_date"].notna()]
    elapsed_years = max(
        (pd.to_datetime(curve["date"]).max() - pd.to_datetime(curve["date"]).min()).days / 365.25,
        1.0 / 252.0,
    )
    summary = pd.DataFrame([{
        "start": pd.to_datetime(curve["date"]).min().date(),
        "end": pd.to_datetime(curve["date"]).max().date(),
        "rebalance": rebalance,
        "rebalance_count": len(trades),
        "executed_rebalance_count": len(executed_trades),
        "cost_bps": cost_bps,
        "top_n": config.top_n_funds,
        "weight_scheme": config.weight_scheme,
        "max_weight": config.max_weight,
        "average_turnover": float(executed_trades["turnover"].mean()),
        "annualized_turnover": float(executed_trades["turnover"].sum() / elapsed_years),
        "total_traded_notional": float(executed_trades["traded_notional"].sum()),
        "total_transaction_cost": float(executed_trades["applied_cost"].sum()),
        "cost_drag": float(curve["gross_equity"].iloc[-1] - curve["net_equity"].iloc[-1]),
        "net_excess_total_return": float(
            metric_by_name.loc["strategy_net", "total_return"]
            - metric_by_name.loc["equal_weight_benchmark", "total_return"]
        ),
        "net_excess_cagr": float(
            metric_by_name.loc["strategy_net", "cagr"]
            - metric_by_name.loc["equal_weight_benchmark", "cagr"]
        ),
        "beat_benchmark": bool(
            metric_by_name.loc["strategy_net", "total_return"]
            > metric_by_name.loc["equal_weight_benchmark", "total_return"]
        ),
        "average_return_coverage": float(curve["return_coverage"].mean()),
    }])
    summary.to_csv(out_dir / "rolling_summary.csv", index=False)

    report_sections = [
        "<h1>Rolling Fund Strategy Backtest</h1>",
        f"<p><strong>Research limitation:</strong> {universe_warning}</p>",
        "<h2>Performance comparison</h2>",
        metrics.to_html(index=False, float_format=lambda value: f"{value:.6f}"),
        "<h2>Turnover and costs</h2>",
        summary.to_html(index=False, float_format=lambda value: f"{value:.6f}"),
        "<h2>Questions answered</h2>",
        f"<p>Net strategy total return: {metric_by_name.loc['strategy_net', 'total_return']:.2%}</p>",
        f"<p>Benchmark total return: {metric_by_name.loc['equal_weight_benchmark', 'total_return']:.2%}</p>",
        f"<p>Beat benchmark: {summary.loc[0, 'beat_benchmark']}</p>",
        f"<p>Annualized turnover: {summary.loc[0, 'annualized_turnover']:.2f}x</p>",
        f"<p>Cost drag on final wealth: {summary.loc[0, 'cost_drag']:.4f}</p>",
        '<p><img src="rolling_equity_curve.png" alt="Strategy and benchmark equity curves"></p>',
    ]
    (out_dir / "rolling_report.html").write_text("\n".join(report_sections), encoding="utf-8")
    manifest = {
        "requested_start": str(start.date()),
        "requested_end": str(end.date()),
        "effective_start": str(pd.to_datetime(curve["date"]).min().date()),
        "effective_end": str(pd.to_datetime(curve["date"]).max().date()),
        "universe_csv": str(config.universe_csv),
        "universe_count": len(universe),
        "universe_sha256": hashlib.sha256("\n".join(universe).encode("utf-8")).hexdigest(),
        "window_trading_days": config.window_days,
        "top_n": config.top_n_funds,
        "weight_scheme": config.weight_scheme,
        "max_weight": config.max_weight,
        "rebalance": rebalance,
        "cost_bps": cost_bps,
        "research_limitations": [universe_warning],
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log(f"[ROLLING] saved: {out_dir / 'rolling_equity_curve.csv'}")
    log(f"[ROLLING] saved: {out_dir / 'rolling_holdings.csv'}")
    log(f"[ROLLING] saved: {out_dir / 'rolling_metrics.csv'}")
    log(f"[ROLLING] saved: {out_dir / 'rolling_summary.csv'}")
    log(f"[ROLLING] saved: {out_dir / 'rolling_report.html'}")
    return curve
