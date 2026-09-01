from __future__ import annotations

import unittest

import pandas as pd

from src.domain.scoring import score_funds


class ScoringDirectionTests(unittest.TestCase):
    def test_less_negative_drawdown_receives_higher_score(self):
        factors = pd.DataFrame({
            "fund_code": ["A", "B", "C"],
            "mdd": [-0.10, -0.20, -0.40],
        })
        scored = score_funds(factors, factor_weights={"mdd": 1.0})
        self.assertEqual(scored.iloc[0]["fund_code"], "A")
        self.assertEqual(scored.iloc[-1]["fund_code"], "C")


if __name__ == "__main__":
    unittest.main()
