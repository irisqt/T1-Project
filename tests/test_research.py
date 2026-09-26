import unittest
from dataclasses import replace
from unittest.mock import patch

from bitget_bot.config import Settings
from bitget_bot.models import Candle, Funding, Instrument, Signal
from bitget_bot.research import backtest, run_research

H = 3_600_000
SPEC = Instrument("BTCUSDT", .001, .001, 5, .01)


def rows(count=120):
    return [Candle(i*H, 100, 100.5, 99.5, 100, 1) for i in range(count)]


def one_signal(symbol, candles, now, config):
    if candles[-1].ts == 106*H:
        return Signal(symbol, 1, 106*H, 100, 98, "execution_test")
    return None


class ResearchTests(unittest.TestCase):
    def test_next_open_entry_same_bar_stop_complete_cash_costs(self):
        data = rows()
        data[107] = Candle(107*H, 101, 102, 97, 100)
        with patch("bitget_bot.research.evaluate", one_signal):
            result = backtest(data, Settings(), instrument=SPEC, funding=[])
        self.assertEqual(result["trade_count"], 1)
        trade = result["trades"][0]
        self.assertEqual(trade["entry_ts"], 107*H)
        self.assertAlmostEqual(trade["entry"], 101*1.0004)
        self.assertEqual(trade["reason"], "stop_intrabar_time_unknown")
        self.assertLess(trade["exit"], trade["entry"]-2)
        self.assertAlmostEqual(result["net_pnl"], sum(t["net_pnl"] for t in result["trades"]), places=7)
        self.assertEqual(result["ending_positions"], [])

    def test_gap_stop_uses_worse_open(self):
        data = rows()
        data[108] = Candle(108*H, 95, 96, 94, 95)
        with patch("bitget_bot.research.evaluate", one_signal):
            result = backtest(data, Settings(), instrument=SPEC, funding=[])
        self.assertAlmostEqual(result["trades"][0]["exit"], 95*.9996)

    def test_funding_cash_cost_and_unknown_label(self):
        data = [Candle(i*H,100,100.5,99.8,100) for i in range(120)]
        # Keep trailing channel below subsequent lows so the position survives.
        data[95] = Candle(95*H,100,100.5,99,100)
        with patch("bitget_bot.research.evaluate", one_signal):
            actual = backtest(data, replace(Settings(), trailing_bars=100), instrument=SPEC,
                              funding=[Funding(112*H,.001)])
        trade = actual["trades"][0]
        self.assertAlmostEqual(trade["funding_pnl"], -trade["qty"]*100*.001)
        self.assertAlmostEqual(actual["net_pnl"], trade["net_pnl"], places=7)
        with patch("bitget_bot.research.evaluate", one_signal):
            estimated = backtest(data, replace(Settings(), trailing_bars=100), instrument=SPEC)
        self.assertEqual(estimated["funding_mode"]["BTCUSDT"], "ADVERSE_ESTIMATE_NOT_VALIDATED")
        self.assertFalse(estimated["live_eligible"])

    def test_mtm_drawdown_and_explicit_end_close(self):
        data = rows()
        data[108] = Candle(108*H,100,100.5,98.1,100)
        with patch("bitget_bot.research.evaluate", one_signal):
            result = backtest(data, replace(Settings(), trailing_bars=200), instrument=SPEC, funding=[])
        self.assertGreater(result["max_drawdown"], result["fees"]/10000)
        self.assertEqual(result["trades"][-1]["reason"], "research_window_end")
        self.assertEqual(result["ending_positions"], [])
        self.assertTrue(result["ending_positions_before_forced_close"])

    def test_future_outside_window_cannot_change_result(self):
        data = rows(130)
        changed = data[:120]+[Candle(i*H,500,600,400,500) for i in range(120,130)]
        with patch("bitget_bot.research.evaluate", one_signal):
            first = backtest(data, Settings(), instrument=SPEC, end_index=120)
            second = backtest(changed, Settings(), instrument=SPEC, end_index=120)
        self.assertEqual(first,second)

    def test_trailing_cannot_act_retrospectively(self):
        data = rows()
        data[107] = Candle(107*H,100,101,99,100)
        with patch("bitget_bot.research.evaluate", one_signal):
            result = backtest(data, Settings(), instrument=SPEC, funding=[])
        self.assertNotEqual(result["trades"][0]["exit_observed_ts"],108*H)

    def test_short_gap_and_funding_sign_are_correct(self):
        def short_signal(symbol, candles, now, config):
            if candles[-1].ts == 106*H:
                return Signal(symbol,-1,106*H,100,102,"short_execution_test")
        with patch("bitget_bot.research.evaluate",short_signal):
            result=backtest(rows(),replace(Settings(),trailing_bars=200),instrument=SPEC,
                            funding=[Funding(112*H,.001)])
        trade=result["trades"][0]
        self.assertAlmostEqual(trade["funding_pnl"],trade["qty"]*.1)
        data=rows()
        data[108]=Candle(108*H,105,106,104,105)
        with patch("bitget_bot.research.evaluate",short_signal):
            stopped=backtest(data,Settings(),instrument=SPEC,funding=[])
        self.assertAlmostEqual(stopped["trades"][0]["exit"],105*1.0004)

    def test_unknown_stop_funding_sequence_never_assumes_receipt(self):
        data=rows()
        data[108]=Candle(108*H,100,101,97,99)
        with patch("bitget_bot.research.evaluate",one_signal):
            received=backtest(data,replace(Settings(),trailing_bars=200),instrument=SPEC,
                             funding=[Funding(108*H+H//2,-.001)])
            paid=backtest(data,replace(Settings(),trailing_bars=200),instrument=SPEC,
                         funding=[Funding(108*H+H//2,.001)])
        self.assertEqual(received["funding_pnl"],0)
        self.assertLess(paid["funding_pnl"],0)

    def test_missing_history_duplicate_funding_rejected(self):
        data = rows()
        with self.assertRaises(ValueError):
            backtest(data[:70]+data[71:],Settings())
        with self.assertRaises(ValueError):
            backtest(data,Settings(),funding=[Funding(112*H,.001),Funding(112*H,.002)])

    def test_holdout_sealed_shared_cash_accounting(self):
        data = rows(145)
        with patch("bitget_bot.research.evaluate", one_signal):
            result = run_research({"BTCUSDT":data,"ETHUSDT":data}, Settings(),
                       instruments={"BTCUSDT":SPEC,"ETHUSDT":replace(SPEC,symbol="ETHUSDT")})
        self.assertFalse(result["holdout"]["evaluated"])
        self.assertEqual(result["holdout"]["results"],[])
        self.assertEqual(len(result["results"]),18)
        self.assertFalse(result["adequate_window_length"])
        for report in result["results"]:
            self.assertEqual(report["initial_equity"],10000)
            self.assertAlmostEqual(report["net_pnl"],sum(t["net_pnl"] for t in report["trades"]),places=7)


if __name__ == "__main__":
    unittest.main()
