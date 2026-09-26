import unittest
from dataclasses import replace

from bitget_bot.config import Settings
from bitget_bot.models import Candle
from bitget_bot.strategy import evaluate, trailing_stop

H = 3_600_000


def trend_rows(count=112):
    rows = []
    for i in range(count):
        close = 100+i*.03
        rows.append(Candle(i*H, close-.02, close+.3, close-.3, close, 10))
    previous = rows[-2].close
    rows[-1] = Candle((count-1)*H, previous, previous+3.2, previous-.2, previous+3, 10)
    return rows


class StrategyTests(unittest.TestCase):
    def test_closed_breakout_and_freshness(self):
        data = trend_rows()
        signal = evaluate("BTCUSDT", data, len(data)*H, Settings())
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, 1)
        self.assertLess(signal.stop, signal.entry)
        self.assertIsNone(evaluate("BTCUSDT", data, len(data)*H+120001, Settings()))

    def test_unclosed_future_prices_cannot_change_signal(self):
        data = trend_rows()
        now = len(data)*H
        future = Candle(now, 1, 10000, .01, 9000, 100)
        self.assertEqual(evaluate("BTCUSDT", data, now, Settings()),
                         evaluate("BTCUSDT", data+[future], now, Settings()))

    def test_gap_duplicate_and_nonfinite_refuse(self):
        data = trend_rows()
        self.assertIsNone(evaluate("BTCUSDT", data[:25]+data[26:], len(data)*H, Settings()))
        self.assertIsNone(evaluate("BTCUSDT", data+[data[-1]], len(data)*H, Settings()))
        data[-1] = replace(data[-1], close=float("nan"))
        self.assertIsNone(evaluate("BTCUSDT", data, len(data)*H, Settings()))

    def test_breakout_excludes_current_bar_and_requires_trend(self):
        data = trend_rows()
        self.assertIsNotNone(evaluate("BTCUSDT", data, len(data)*H, Settings()))
        flat = [Candle(i*H, 100, 101, 99, 100) for i in range(112)]
        self.assertIsNone(evaluate("BTCUSDT", flat, len(flat)*H, Settings()))

    def test_short_breakout_is_symmetric(self):
        original = trend_rows()
        data = [Candle(b.ts, 220-b.open, 220-b.low, 220-b.high, 220-b.close, b.volume)
                for b in original]
        signal = evaluate("BTCUSDT", data, len(data)*H, Settings())
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, -1)
        self.assertGreater(signal.stop, signal.entry)

    def test_trailing_monotone_uses_prior_channel(self):
        data = trend_rows()
        before = trailing_stop(1, 90, data)
        changed = data[:-1]+[Candle(data[-1].ts, 100, 1000, 1, 500)]
        self.assertEqual(before, trailing_stop(1, 90, changed))
        self.assertGreaterEqual(trailing_stop(1, 105, data), 105)
        self.assertLessEqual(trailing_stop(-1, 103, data), 103)


if __name__ == "__main__":
    unittest.main()
