from __future__ import annotations

import unittest

from scripts.build_equity_universe import base_name, classify_share, reason_for_type


class UniverseClassificationTests(unittest.TestCase):
    def test_share_classification_handles_labelled_and_original_shares(self):
        self.assertEqual(classify_share("示例偏股混合A"), "A")
        self.assertEqual(classify_share("示例偏股混合C"), "C")
        self.assertEqual(classify_share("示例偏股混合(后端)"), "B")
        self.assertEqual(classify_share("示例偏股混合"), "original")

    def test_base_name_removes_share_suffix(self):
        self.assertEqual(base_name("示例偏股混合A"), base_name("示例偏股混合C"))
        self.assertEqual(base_name("示例偏股混合(后端)"), base_name("示例偏股混合"))

    def test_scheme_b_type_filter_is_explicit(self):
        self.assertEqual(reason_for_type({"fund_type": "股票型", "fund_name": "示例股票基金A"}), "")
        self.assertEqual(reason_for_type({"fund_type": "混合型-偏股", "fund_name": "示例偏股基金A"}), "")
        self.assertEqual(reason_for_type({"fund_type": "债券型-长债", "fund_name": "示例债券A"}), "TYPE_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
