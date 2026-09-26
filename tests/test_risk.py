import math
import unittest
from dataclasses import replace

from bitget_bot.config import Settings
from bitget_bot.models import Instrument
from bitget_bot.risk import size_position

SPEC = Instrument("BTCUSDT", .001, .001, 5, .01)


class RiskTests(unittest.TestCase):
    def test_dynamic_leverage_and_cash_loss_independence(self):
        cfg = Settings()
        narrow = size_position(10000, 100, 99.5, SPEC, cfg)
        broad = size_position(10000, 100, 94, SPEC, cfg)
        self.assertIsNotNone(narrow)
        self.assertIsNotNone(broad)
        self.assertGreater(narrow.leverage, broad.leverage)
        self.assertTrue(5 <= broad.leverage <= narrow.leverage <= 30)
        self.assertLessEqual(narrow.risk_cash, 10)
        self.assertLessEqual(broad.risk_cash, 5)
        fixed = size_position(10000, 100, 99.5, SPEC, replace(cfg, max_leverage=5))
        self.assertAlmostEqual(fixed.qty, narrow.qty)

    def test_margin_gross_and_cluster_caps(self):
        cfg = Settings()
        sized = size_position(10000, 100, 99.5, SPEC, cfg,
                              open_risk=69, used_margin=2990, gross_notional=19990)
        self.assertIsNotNone(sized)
        self.assertLessEqual(sized.risk_cash, 1)
        self.assertLessEqual(sized.margin, 10)
        self.assertLessEqual(sized.notional, 10)
        for kwargs in ({"open_risk": 70}, {"used_margin": 3000}, {"gross_notional": 20000}):
            self.assertIsNone(size_position(10000, 100, 99, SPEC, cfg, **kwargs))

    def test_drawdown_reduces_then_blocks(self):
        base = size_position(10000, 100, 99, SPEC, Settings())
        reduced = size_position(10000, 100, 99, SPEC, Settings(), drawdown=.06)
        self.assertLessEqual(reduced.risk_cash, base.risk_cash*.501)
        self.assertIsNone(size_position(10000, 100, 99, SPEC, Settings(), drawdown=.08))

    def test_invalid_metadata_and_unsafe_leverage_refuse(self):
        for value in (math.nan, math.inf, -1, 0):
            self.assertIsNone(size_position(value, 100, 99, SPEC, Settings()))
        for key, value in (("qty_step", 0), ("price_tick", math.nan),
                           ("maintenance_margin", .25), ("max_leverage", 4), ("status", "offline"), ("status", "listed")):
            self.assertIsNone(size_position(10000, 100, 99, replace(SPEC, **{key: value}), Settings()))
        self.assertIsNone(size_position(10000, 100, 100, SPEC, Settings()))

    def test_minimum_never_increases_budget(self):
        self.assertIsNone(size_position(100, 100, 99, replace(SPEC, min_qty=100), Settings()))

    def test_contract_step_is_floored(self):
        result = size_position(10000, 100, 99, replace(SPEC, qty_step=.03), Settings())
        self.assertAlmostEqual(result.qty/.03, round(result.qty/.03), places=8)
        self.assertLessEqual(result.risk_cash, 10)


if __name__ == "__main__":
    unittest.main()
