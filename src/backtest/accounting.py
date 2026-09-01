from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import wealth_index


def normalize_rebalance_weights(weights: pd.DataFrame) -> pd.DataFrame:
    """Normalize each rebalance row; missing holdings mean a zero target weight."""
    if weights is None or weights.empty:
        return pd.DataFrame()
    normalized = weights.copy().sort_index().fillna(0.0).astype(float)
    denominator = normalized.abs().sum(axis=1).replace(0.0, np.nan)
    return normalized.div(denominator, axis=0).fillna(0.0)


def cap_weights(weights: pd.Series, max_weight: float) -> pd.Series:
    """Cap long-only weights and redistribute excess until the row sums to one."""
    if weights is None or weights.empty:
        return pd.Series(dtype=float)
    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be in (0, 1]")
    result = pd.to_numeric(weights, errors="coerce").fillna(0.0).clip(lower=0.0).copy()
    result = result / (result.sum() or 1.0)
    if len(result) * max_weight < 1.0 - 1e-12:
        raise ValueError("max_weight is too low for the number of holdings")
    for _ in range(len(result) + 1):
        over = result > max_weight + 1e-12
        if not over.any():
            break
        excess = float((result[over] - max_weight).sum())
        result.loc[over] = max_weight
        free = result < max_weight - 1e-12
        if not free.any():
            break
        base = result.loc[free]
        result.loc[free] += excess * base / (base.sum() or 1.0)
    return result / (result.sum() or 1.0)


def turnover_table(
    weights: pd.DataFrame,
    *,
    cost_bps: float = 0.0,
    charge_initial: bool = False,
) -> pd.DataFrame:
    """Calculate one-way turnover, traded notional and transaction costs."""
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    normalized = normalize_rebalance_weights(weights)
    if normalized.empty:
        return pd.DataFrame(columns=["date", "turnover", "traded_notional", "cost"])

    changes = normalized.diff()
    if charge_initial:
        changes.iloc[0] = normalized.iloc[0]
    else:
        changes.iloc[0] = 0.0
    traded_notional = changes.abs().sum(axis=1)

    return pd.DataFrame({
        "date": normalized.index,
        "turnover": 0.5 * traded_notional,
        "traded_notional": traded_notional,
        "cost": traded_notional * cost_bps / 10000.0,
    }).reset_index(drop=True)


def simulate_rebalance_weights(
    fund_returns: pd.DataFrame,
    rebalance_weights: pd.DataFrame,
    *,
    benchmark_returns: pd.Series | None = None,
    cost_bps: float = 0.0,
    charge_initial: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply target weights from the next trading day and deduct trading costs."""
    if fund_returns is None or fund_returns.empty:
        raise ValueError("fund_returns must not be empty")
    targets = normalize_rebalance_weights(rebalance_weights)
    if targets.empty:
        raise ValueError("rebalance_weights must not be empty")

    returns = fund_returns.copy().sort_index()
    returns.index = pd.to_datetime(returns.index)
    targets.index = pd.to_datetime(targets.index)
    all_columns = returns.columns.union(targets.columns)
    returns = returns.reindex(columns=all_columns)
    targets = targets.reindex(columns=all_columns, fill_value=0.0)

    start = targets.index.min()
    returns = returns.loc[returns.index >= start]
    daily_targets = targets.reindex(returns.index).ffill().fillna(0.0)
    active_weights = daily_targets.shift(1).fillna(0.0)

    valid_returns = returns.notna().astype(float)
    gross_return = (active_weights * returns.fillna(0.0)).sum(axis=1)
    invested_weight = active_weights.abs().sum(axis=1)
    return_coverage = (
        (active_weights.abs() * valid_returns).sum(axis=1)
        .div(invested_weight.replace(0.0, np.nan))
        .fillna(0.0)
    )

    trades = turnover_table(targets, cost_bps=cost_bps, charge_initial=charge_initial)
    trades["effective_date"] = pd.NaT
    trades["applied_cost"] = 0.0
    daily_cost = pd.Series(0.0, index=returns.index)
    for trade in trades.itertuples(index=False):
        effective_dates = returns.index[returns.index > pd.Timestamp(trade.date)]
        if len(effective_dates):
            effective_date = effective_dates[0]
            daily_cost.loc[effective_date] += float(trade.cost)
            trade_index = trades.index[trades["date"] == trade.date]
            trades.loc[trade_index, "effective_date"] = effective_date
            trades.loc[trade_index, "applied_cost"] = float(trade.cost)

    active_dates = invested_weight > 0.0
    returns = returns.loc[active_dates]
    gross_return = gross_return.loc[active_dates]
    daily_cost = daily_cost.loc[active_dates]
    return_coverage = return_coverage.loc[active_dates]
    net_return = gross_return - daily_cost
    if benchmark_returns is None:
        benchmark = returns.mean(axis=1, skipna=True).fillna(0.0)
    else:
        benchmark = pd.to_numeric(benchmark_returns, errors="coerce").reindex(returns.index).fillna(0.0)

    curve = pd.DataFrame({
        "date": returns.index,
        "gross_return": gross_return.values,
        "transaction_cost": daily_cost.values,
        "net_return": net_return.values,
        "benchmark_return": benchmark.values,
        "return_coverage": return_coverage.values,
    })
    curve["gross_equity"] = wealth_index(curve["gross_return"])
    curve["net_equity"] = wealth_index(curve["net_return"])
    curve["benchmark_equity"] = wealth_index(curve["benchmark_return"])
    curve["relative_equity"] = curve["net_equity"] / curve["benchmark_equity"]
    curve["daily_excess_return"] = curve["net_return"] - curve["benchmark_return"]
    return curve, trades
