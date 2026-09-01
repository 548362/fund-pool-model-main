from __future__ import annotations

import unittest

from src.backtest.score_schemes import SCORE_SCHEMES, validate_score_schemes


class ScoreSchemeTests(unittest.TestCase):
    def test_builtins_are_valid(self):
        validate_score_schemes()
        self.assertEqual(set(SCORE_SCHEMES), {"baseline_corrected", "return_ir", "sharpe_ir", "return_sharpe_ir"})

    def test_return_ir_uses_only_declared_factors(self):
        self.assertEqual(set(SCORE_SCHEMES["return_ir"]), {"ann_return", "ir"})

    def test_baseline_uses_correct_mdd_direction(self):
        self.assertGreater(SCORE_SCHEMES["baseline_corrected"]["mdd"], 0)


if __name__ == "__main__":
    unittest.main()
