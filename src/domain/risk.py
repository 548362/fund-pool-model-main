from __future__ import annotations
import pandas as pd


def check_risk(
    df_scores: pd.DataFrame,
    *,
    expected_count: int | None = None,
    top_n: int | None = None,
) -> list[str]:
    warns = []
    if df_scores is None or df_scores.empty:
        warns.append("Scores empty")
        return warns
    cols = [c for c in df_scores.columns if c not in ("fund_code", "score", "rank")]
    if not cols:
        warns.append("No valid factor columns")
    if df_scores["score"].nunique() <= 3:
        warns.append("Low score differentiation, check factors/window")
    if expected_count and len(df_scores) < max(1, int(expected_count * 0.8)):
        warns.append(f"Only {len(df_scores)}/{expected_count} funds have valid scores")
    if top_n and len(df_scores) < top_n:
        warns.append(f"Only {len(df_scores)} funds are available for requested Top-{top_n}")
    return warns
