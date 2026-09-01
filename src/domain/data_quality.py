from __future__ import annotations

import pandas as pd

from ..common.utils import norm_code


def check_nav_quality(
    df_nav: pd.DataFrame,
    df_ret: pd.DataFrame,
    universe: list[str],
    *,
    as_of: str,
    stale_days: int = 7,
) -> list[str]:
    """Return actionable warnings for missing, stale or suspicious NAV data."""
    warnings: list[str] = []
    expected = {norm_code(code) for code in universe if norm_code(code)}
    if df_nav is None or df_nav.empty:
        return ["NAV data is empty"]

    nav = df_nav.copy()
    nav["fund_code"] = nav["fund_code"].map(norm_code)
    nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
    present = set(nav["fund_code"].dropna())
    missing = sorted(expected - present)
    if missing:
        warnings.append(f"Missing NAV for {len(missing)} funds: {', '.join(missing)}")

    latest = nav.groupby("fund_code")["date"].max().dropna()
    if not latest.empty:
        pool_latest = latest.max()
        lagging = latest[(pool_latest - latest).dt.days > stale_days].index.tolist()
        if lagging:
            warnings.append(f"NAV is stale for {len(lagging)} funds relative to the pool latest date")
        age = (pd.Timestamp(as_of).normalize() - pool_latest.normalize()).days
        if age > stale_days:
            warnings.append(f"Pool latest NAV is stale: {age} calendar days old ({pool_latest.date()})")

    metadata_cols = [column for column in ("daily_return", "acc_nav") if column in nav.columns]
    if metadata_cols:
        coverage = nav[metadata_cols].notna().any(axis=1).mean()
        if coverage < 0.95:
            warnings.append(f"Total-return metadata coverage is only {coverage:.1%}; unit NAV fallback is in use")
    else:
        warnings.append("Total-return metadata is unavailable; unit NAV fallback is in use")

    if df_ret is not None and not df_ret.empty:
        extreme = pd.to_numeric(df_ret["ret"], errors="coerce").abs() > 0.50
        if extreme.any():
            warnings.append(f"Detected {int(extreme.sum())} daily returns above 50%; inspect corporate actions/data")
    return warnings
