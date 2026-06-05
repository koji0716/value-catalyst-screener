import unittest

from src.analysis.metrics import quality_score, safety_score
from src.analysis.momentum import momentum_score
from src.analysis.risk import risk_score
from src.analysis.valuation import valuation_score


class MetricScoreTests(unittest.TestCase):
    def test_valuation_score_rewards_low_multiples(self):
        self.assertEqual(valuation_score(per=7, pbr=0.6, ev_ebitda=4, fcf_yield=0.12), 100)

    def test_quality_score_caps_at_100(self):
        self.assertEqual(quality_score(roe=20, operating_margin=20, fcf_margin=15, revenue_growth=12), 100)

    def test_safety_score_uses_equity_and_cash_flow(self):
        self.assertEqual(safety_score(equity_ratio=40, net_debt_ebitda=0.5, operating_cf_positive=True), 85)

    def test_momentum_score_handles_mixed_returns(self):
        self.assertEqual(momentum_score(return_3m=0.06, return_6m=-0.05, above_200ma=True, volume_change=1.3), 63)

    def test_risk_score_caps_at_100(self):
        self.assertEqual(
            risk_score(
                {
                    "negative_equity": True,
                    "going_concern": True,
                    "operating_cf_negative_3y": True,
                    "low_liquidity": True,
                }
            ),
            100,
        )


if __name__ == "__main__":
    unittest.main()

