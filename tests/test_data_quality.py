from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src._config import Config
from src.data.repository import Repository
from src.domain.data_quality import check_nav_quality
from src.domain.factors import compute_factors


class ReturnSeriesTests(unittest.TestCase):
    def test_provider_daily_return_takes_priority_over_unit_nav(self):
        nav = pd.DataFrame({
            "fund_code": ["000001"] * 3,
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "nav": [1.0, 0.8, 0.7],
            "acc_nav": [1.0, 1.0, 1.0],
            "daily_return": [None, 0.02, -0.01],
        })
        returns = Repository.to_returns(nav)
        self.assertAlmostEqual(float(returns.iloc[0]["ret"]), 0.02)
        self.assertAlmostEqual(float(returns.iloc[1]["ret"]), -0.01)

    def test_factor_window_requires_declared_observations(self):
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        returns = pd.DataFrame({"fund_code": "000001", "date": dates, "ret": 0.01})
        factors = compute_factors(returns, window=5)
        self.assertEqual(len(factors), 1)
        self.assertEqual(len(compute_factors(returns.iloc[:4], window=5)), 0)


class DataQualityTests(unittest.TestCase):
    def test_quality_reports_missing_and_stale_funds(self):
        nav = pd.DataFrame({
            "fund_code": ["000001"],
            "date": pd.to_datetime(["2024-01-01"]),
            "nav": [1.0],
            "acc_nav": [None],
            "daily_return": [None],
        })
        warnings = check_nav_quality(nav, pd.DataFrame(), ["000001", "000002"], as_of="2024-01-10")
        self.assertTrue(any("Missing NAV" in item for item in warnings))
        self.assertTrue(any("stale" in item.lower() for item in warnings))


if __name__ == "__main__":
    unittest.main()
