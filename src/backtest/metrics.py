from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd



TRADING_DAYS = 252


def wealth_index(returns: pd.Series, initial_value: float = 1.0) -> pd.Series:
    """Convert periodic returns into a wealth index."""
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    return initial_value * (1.0 + clean).cumprod()


def performance_metrics(
    returns: pd.Series,
    *,
    dates: pd.Series | pd.Index | None = None,
    periods_per_year: int = TRADING_DAYS,
) -> dict[str, float | int | str]:
    """Calculate consistently defined performance metrics from daily returns."""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return {
            "start": "",
            "end": "",
            "observations": 0,
            "final_equity": np.nan,
            "total_return": np.nan,
            "cagr": np.nan,
            "annual_volatility": np.nan,
            "sharpe": np.nan,
            "max_drawdown": np.nan,
        }

    if (clean <= -1.0).any():
        raise ValueError("returns must be greater than -100%")

    wealth = wealth_index(clean)
    total_return = float(wealth.iloc[-1] - 1.0)

    date_index = None
    if dates is not None:
        parsed = pd.to_datetime(pd.Index(dates), errors="coerce")
        if len(parsed) == len(returns):
            date_index = parsed[pd.notna(pd.to_numeric(returns, errors="coerce"))]

    if date_index is not None and len(date_index) > 1:
        elapsed_years = (date_index.max() - date_index.min()).days / 365.25
    else:
        elapsed_years = len(clean) / periods_per_year
    elapsed_years = max(float(elapsed_years), 1.0 / periods_per_year)

    cagr = float(wealth.iloc[-1] ** (1.0 / elapsed_years) - 1.0)
    annual_volatility = float(clean.std(ddof=0) * np.sqrt(periods_per_year))
    annualized_mean = float(clean.mean() * periods_per_year)
    sharpe = annualized_mean / annual_volatility if annual_volatility > 0 else np.nan
    max_drawdown = float((wealth / wealth.cummax() - 1.0).min())

    return {
        "start": str(date_index.min().date()) if date_index is not None and len(date_index) else "",
        "end": str(date_index.max().date()) if date_index is not None and len(date_index) else "",
        "observations": int(len(clean)),
        "final_equity": float(wealth.iloc[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": annual_volatility,
        "sharpe": float(sharpe),
        "max_drawdown": max_drawdown,
    }


def performance_table(
    return_series: Mapping[str, pd.Series],
    *,
    dates: pd.Series | pd.Index | None = None,
) -> pd.DataFrame:
    """Build a comparable metrics table for several return series."""
    rows = []
    for name, returns in return_series.items():
        rows.append({"portfolio": name, **performance_metrics(returns, dates=dates)})
    return pd.DataFrame(rows)
