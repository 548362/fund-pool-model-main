from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .._config import Config
from .._exceptions import BacktestError
from ..data.repository import Repository
from ..domain.factors import compute_factors
from ..domain.scoring import score_funds
from .rolling import _first_usable_date, _month_end_dates, _quarter_end_dates


FACTOR_NAMES = ["ann_return", "ann_vol", "down_vol", "mdd", "sharpe", "ir"]


def _diagnostic_returns(config: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load point-in-time returns restricted to the configured universe."""
    universe = pd.read_csv(config.universe_csv, dtype={"fund_code": str})["fund_code"]
    universe = universe.astype(str).str.zfill(6).drop_duplicates().tolist()
    repo = Repository(config)
    nav = repo.load_nav(universe, since=config.since_date)
    returns = repo.to_returns(nav)
    returns["date"] = pd.to_datetime(returns["date"])
    returns = returns.sort_values("date")
    if returns.empty:
        raise BacktestError("No returns available for factor diagnostics")
    ret_wide = returns.pivot_table(index="date", columns="fund_code", values="ret", aggfunc="last").sort_index()
    benchmark = ret_wide.mean(axis=1, skipna=True)
    return returns, benchmark


def run_factor_correlation_diagnostics(
    config: Config,
    *,
    start_date: str,
    end_date: str,
    rebalance: str = "month",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate cross-sectional Spearman correlations at each rebalance date."""
    returns, benchmark = _diagnostic_returns(config)
    ret_wide = returns.pivot_table(index="date", columns="fund_code", values="ret", aggfunc="last").sort_index()
    dates = ret_wide.index[(ret_wide.index >= pd.Timestamp(start_date)) & (ret_wide.index <= pd.Timestamp(end_date))]
    if rebalance == "month":
        rebalance_dates = _month_end_dates(dates)
    elif rebalance == "quarter":
        rebalance_dates = _quarter_end_dates(dates)
    else:
        raise ValueError("rebalance must be 'month' or 'quarter'")
    if len(dates) == 0:
        raise BacktestError("No dates available for factor correlations")
    first_usable = _first_usable_date(dates, config.window_days)
    rebalance_dates = rebalance_dates[rebalance_dates >= first_usable]

    rows: list[dict] = []
    for rebalance_date in rebalance_dates:
        hist = returns[returns["date"] <= rebalance_date]
        factors = compute_factors(
            hist,
            bench=benchmark[benchmark.index <= rebalance_date],
            window=config.window_days,
        )
        available = [name for name in FACTOR_NAMES if name in factors.columns]
        for i, factor_a in enumerate(available):
            for factor_b in available[i + 1 :]:
                sample = factors[[factor_a, factor_b]].apply(pd.to_numeric, errors="coerce").dropna()
                if len(sample) < 3:
                    continue
                correlation = sample[factor_a].rank(method="average").corr(
                    sample[factor_b].rank(method="average")
                )
                if pd.isna(correlation):
                    continue
                rows.append({
                    "rebalance_date": rebalance_date.date(),
                    "factor_a": factor_a,
                    "factor_b": factor_b,
                    "correlation": float(correlation),
                    "sample_size": int(len(sample)),
                })
    by_rebalance = pd.DataFrame(rows)
    if by_rebalance.empty:
        raise BacktestError("No factor correlations could be calculated")
    summary = (
        by_rebalance.groupby(["factor_a", "factor_b"], as_index=False)
        .agg(
            mean_correlation=("correlation", "mean"),
            median_correlation=("correlation", "median"),
            min_correlation=("correlation", "min"),
            max_correlation=("correlation", "max"),
            periods=("correlation", "count"),
        )
        .sort_values("mean_correlation", ascending=False)
    )
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_rebalance.to_csv(out_dir / "factor_correlation_by_rebalance.csv", index=False)
    summary.to_csv(out_dir / "factor_correlation_mean.csv", index=False)
    return by_rebalance, summary


def run_factor_group_diagnostics(
    config: Config,
    *,
    start_date: str,
    end_date: str,
    rebalance: str = "month",
    groups: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Measure next-period returns of point-in-time factor quantiles."""
    if groups < 2:
        raise ValueError("groups must be at least 2")
    universe = pd.read_csv(config.universe_csv, dtype={"fund_code": str})["fund_code"]
    universe = universe.str.zfill(6).drop_duplicates().tolist()
    repo = Repository(config)
    nav = repo.load_nav(universe, since=config.since_date)
    returns = repo.to_returns(nav)
    returns["date"] = pd.to_datetime(returns["date"])
    returns = returns.sort_values("date")
    if returns.empty:
        raise BacktestError("No returns available for factor diagnostics")

    ret_wide = returns.pivot_table(index="date", columns="fund_code", values="ret", aggfunc="last").sort_index()
    benchmark = ret_wide.mean(axis=1, skipna=True)
    dates = ret_wide.index[(ret_wide.index >= pd.Timestamp(start_date)) & (ret_wide.index <= pd.Timestamp(end_date))]
    if rebalance == "month":
        rebalance_dates = _month_end_dates(dates)
    elif rebalance == "quarter":
        rebalance_dates = _quarter_end_dates(dates)
    else:
        raise ValueError("rebalance must be 'month' or 'quarter'")
    first_usable = _first_usable_date(dates, config.window_days)
    rebalance_dates = rebalance_dates[rebalance_dates >= first_usable]

    detail_rows: list[dict] = []
    factor_names = list(config.factor_weights)
    directions = {name: 1.0 if weight >= 0 else -1.0 for name, weight in config.factor_weights.items()}
    directions["score"] = 1.0
    for rebalance_date, next_date in zip(rebalance_dates[:-1], rebalance_dates[1:]):
        hist = returns[returns["date"] <= rebalance_date]
        factors = compute_factors(
            hist, bench=benchmark[benchmark.index <= rebalance_date], window=config.window_days
        )
        scores = score_funds(factors, factor_weights=config.factor_weights)
        if factors.empty or scores.empty:
            continue
        signals = factors[["fund_code", *[f for f in factor_names if f in factors.columns]]].merge(
            scores[["fund_code", "score"]], on="fund_code", how="inner"
        )
        forward_window = ret_wide.loc[(ret_wide.index > rebalance_date) & (ret_wide.index <= next_date)]
        forward = ((1.0 + forward_window).prod(axis=0, min_count=1) - 1.0).rename("forward_return")
        for factor in [*factor_names, "score"]:
            if factor not in signals.columns:
                continue
            sample = signals[["fund_code", factor]].merge(
                forward.rename_axis("fund_code").reset_index(), on="fund_code", how="inner"
            ).dropna()
            if len(sample) < groups * 2 or sample[factor].nunique() < groups:
                continue
            preferred_signal = sample[factor] * directions[factor]
            sample["quantile"] = pd.qcut(
                preferred_signal.rank(method="first"), groups, labels=range(1, groups + 1)
            ).astype(int)
            grouped = sample.groupby("quantile")["forward_return"].agg(["mean", "count"])
            for quantile, row in grouped.iterrows():
                detail_rows.append({
                    "rebalance_date": rebalance_date.date(),
                    "next_rebalance_date": next_date.date(),
                    "factor": factor,
                    "quantile": int(quantile),
                    "fund_count": int(row["count"]),
                    "forward_return": float(row["mean"]),
                })

    detail = pd.DataFrame(detail_rows)
    if detail.empty:
        raise BacktestError("No factor groups could be formed")

    summary_rows: list[dict] = []
    for (factor, quantile), group in detail.groupby(["factor", "quantile"]):
        period_returns = group.sort_values("rebalance_date")["forward_return"]
        summary_rows.append({
            "factor": factor,
            "quantile": int(quantile),
            "periods": len(period_returns),
            "mean_forward_return": float(period_returns.mean()),
            "median_forward_return": float(period_returns.median()),
            "positive_rate": float((period_returns > 0).mean()),
            "cumulative_return": float((1.0 + period_returns).prod() - 1.0),
        })
    summary = pd.DataFrame(summary_rows)

    spread_rows: list[dict] = []
    for factor, group in detail.groupby("factor"):
        pivot = group.pivot(index="rebalance_date", columns="quantile", values="forward_return").dropna()
        spread = pivot[groups] - pivot[1]
        quantile_means = group.groupby("quantile")["forward_return"].mean()
        spread_rows.append({
            "factor": factor,
            "periods": len(spread),
            "high_minus_low_mean": float(spread.mean()),
            "high_beats_low_rate": float((spread > 0).mean()),
            "quantile_monotonic_correlation": float(
                pd.Series(quantile_means.index, index=quantile_means.index)
                .rank()
                .corr(quantile_means.rank())
            ),
        })
    spreads = pd.DataFrame(spread_rows).sort_values("high_minus_low_mean", ascending=False)

    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out_dir / "factor_group_returns.csv", index=False)
    summary.to_csv(out_dir / "factor_group_summary.csv", index=False)
    spreads.to_csv(out_dir / "factor_spread_summary.csv", index=False)
    return detail, summary, spreads
