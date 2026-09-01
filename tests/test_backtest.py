from __future__ import annotations

import unittest

import pandas as pd

from src.backtest.accounting import cap_weights, simulate_rebalance_weights, turnover_table
from src.backtest.metrics import performance_metrics


class BacktestAccountingTests(unittest.TestCase):
    def test_cap_weights_redistributes_excess(self):
        capped = cap_weights(pd.Series({"A": 0.8, "B": 0.1, "C": 0.1}), 0.4)
        self.assertAlmostEqual(capped.sum(), 1.0)
        self.assertLessEqual(capped.max(), 0.4 + 1e-12)

    def test_turnover_and_cost_use_explicit_conventions(self):
        dates = pd.to_datetime(["2024-01-02", "2024-02-01"])
        weights = pd.DataFrame(
            [[1.0, 0.0], [0.0, 1.0]],
            index=dates,
            columns=["A", "B"],
        )

        trades = turnover_table(weights, cost_bps=10.0)

        self.assertAlmostEqual(trades.loc[0, "turnover"], 0.0)
        self.assertAlmostEqual(trades.loc[1, "turnover"], 1.0)
        self.assertAlmostEqual(trades.loc[1, "traded_notional"], 2.0)
        self.assertAlmostEqual(trades.loc[1, "cost"], 0.002)

    def test_weights_take_effect_next_day_and_cost_hits_rebalance(self):
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
        returns = pd.DataFrame(
            {"A": [0.0, 0.10, 0.0], "B": [0.0, 0.0, 0.20]},
            index=dates,
        )
        weights = pd.DataFrame(
            [[1.0, 0.0], [0.0, 1.0]],
            index=dates[:2],
            columns=["A", "B"],
        )

        curve, trades = simulate_rebalance_weights(returns, weights, cost_bps=10.0)

        self.assertEqual(curve["date"].tolist(), dates[1:].tolist())
        self.assertAlmostEqual(curve.loc[0, "gross_return"], 0.10)
        self.assertAlmostEqual(curve.loc[1, "gross_return"], 0.20)
        self.assertAlmostEqual(curve.loc[1, "transaction_cost"], 0.002)
        self.assertAlmostEqual(curve.loc[1, "net_return"], 0.198)
        self.assertEqual(pd.Timestamp(trades.loc[1, "effective_date"]), dates[2])
        self.assertAlmostEqual(trades.loc[1, "applied_cost"], 0.002)

    def test_omitted_holding_is_not_forward_filled_at_rebalance(self):
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
        returns = pd.DataFrame(
            {"A": [0.0, 0.0, 0.50], "B": [0.0, 0.0, 0.10]},
            index=dates,
        )
        weights = pd.DataFrame(
            [[1.0, 0.0], [0.0, 1.0]],
            index=dates[:2],
            columns=["A", "B"],
        )

        curve, _ = simulate_rebalance_weights(returns, weights)

        self.assertAlmostEqual(curve.loc[1, "gross_return"], 0.10)


class PerformanceMetricTests(unittest.TestCase):
    def test_total_return_and_drawdown(self):
        returns = pd.Series([0.10, -0.10])
        metrics = performance_metrics(returns)

        self.assertAlmostEqual(metrics["total_return"], -0.01)
        self.assertAlmostEqual(metrics["final_equity"], 0.99)
        self.assertAlmostEqual(metrics["max_drawdown"], -0.10)


if __name__ == "__main__":
    unittest.main()
