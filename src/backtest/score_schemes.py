"""Named scoring specifications used by factor comparison experiments."""

from __future__ import annotations

from typing import Mapping


SCORE_SCHEMES: dict[str, dict[str, float]] = {
    "baseline_corrected": {
        "ann_return": 0.35,
        "ann_vol": -0.15,
        "down_vol": -0.10,
        "mdd": 0.10,
        "sharpe": 0.35,
        "ir": 0.15,
    },
    "return_ir": {"ann_return": 0.40, "ir": 0.60},
    "sharpe_ir": {"sharpe": 0.50, "ir": 0.50},
    "return_sharpe_ir": {"ann_return": 0.40, "sharpe": 0.30, "ir": 0.30},
}


def validate_score_schemes(schemes: Mapping[str, Mapping[str, float]] = SCORE_SCHEMES) -> None:
    """Reject malformed experiment definitions before an expensive backtest."""
    if not schemes:
        raise ValueError("at least one score scheme is required")
    for name, weights in schemes.items():
        if not name or not weights:
            raise ValueError("scheme names and weights must be non-empty")
        if any(not isinstance(factor, str) or not factor for factor in weights):
            raise ValueError(f"{name}: factor names must be non-empty strings")
        if any(not isinstance(weight, (int, float)) for weight in weights.values()):
            raise ValueError(f"{name}: weights must be numeric")
        if sum(abs(float(weight)) for weight in weights.values()) <= 0:
            raise ValueError(f"{name}: at least one non-zero weight is required")

