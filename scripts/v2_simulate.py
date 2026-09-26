from __future__ import annotations

from src.bitget_bot.strategy_v2 import FeatureBook, candidate, Policy, NAMES
import src.bitget_bot.models as models
import src.bitget_bot.risk as risk
Instrument = models.Instrument
size_position = risk.size_position
"""Reproducible chronological research with shared cash and explicit limitations.

No private API or credential path exists here. Candidate comparisons never
select or promote a strategy automatically. Hourly execution is approximate.
"""


from bisect import bisect_right
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import math

from src.bitget_bot.models import Instrument
from src.bitget_bot.risk import size_position
from src.bitget_bot.strategy import _valid

HOUR_MS = 3_600_000
CANDIDATES = ("breakout24", "breakout48", "momentum48")


def _candidate(config, name):
    if name == "breakout24":
        return replace(config, strategy="breakout", breakout_bars=24)
    if name == "breakout48":
        return replace(config, strategy="breakout", breakout_bars=48)
    if name == "momentum48":
        return replace(config, strategy="momentum", momentum_bars=48)
    raise ValueError("unknown preregistered candidate")


def _warmup(config):
    return max(config.ema_period+config.slope_bars, config.atr_period+1,
               config.breakout_bars+1, config.momentum_bars+1)


def _funding_events(events):
    if events is None:
        return None
    result = []
    seen = set()
    for event in events:
        stamp, rate = event.ts, event.rate
        if (not isinstance(stamp, int) or stamp < 0 or stamp in seen
                or not math.isfinite(rate) or abs(rate) > .1):
            raise ValueError("invalid or duplicate funding event")
        seen.add(stamp)
        result.append((stamp, rate))
    return sorted(result)


def _simulate(dataset, config, instruments, funding, start_index, end_index, policy=None):
    config.validate()
    if not dataset:
        raise ValueError("no candles")
    symbols = sorted(dataset)
    streams = {s: list(dataset[s]) for s in symbols}
    first = streams[symbols[0]]
    if not _valid(first, config.candle_interval_ms):
        raise ValueError("invalid, missing or duplicate hourly candles")
    timeline = [bar.ts for bar in first]
    for symbol, rows in streams.items():
        if not _valid(rows, config.candle_interval_ms) or [bar.ts for bar in rows] != timeline:
            raise ValueError("portfolio requires identical complete hourly timelines")
    start = _warmup(config) if start_index is None else start_index
    end = len(first) if end_index is None else end_index
    if not isinstance(start, int) or not isinstance(end, int) or start < _warmup(config) or not start < end <= len(first):
        raise ValueError("evaluation needs sufficient warmup and a nonempty chronological window")
    instruments = instruments or {}
    guessed = sorted(set(symbols)-set(instruments))
    specs = {s: instruments.get(s, Instrument(s, .000001, .000001, 5, .00001)) for s in symbols}
    for symbol, spec in specs.items():
        if spec.symbol != symbol or any(not math.isfinite(v) or v <= 0 for v in
                (spec.qty_step, spec.min_qty, spec.min_notional, spec.price_tick)):
            raise ValueError("invalid contract metadata")
    rates = {s: _funding_events((funding or {}).get(s)) for s in symbols}
    rate_times = {s: [stamp for stamp, _ in events] if events is not None else []
                  for s, events in rates.items()}
    cash = float(config.initial_equity)
    positions, pending, last_exit = {}, {}, {}
    trades, equity_curve = [], []
    peak, max_dd = cash, 0.0
    fees, funding_total, refused = 0.0, 0.0, 0
    pause_until = 0
    permanent_halt = None
    closed_equity_history = []
    fee_rate = config.fee_bps/10000
    slip = config.slippage_bps/10000

    def equity(prices):
        return cash + sum(p["side"]*(prices[s]-p["entry"])*p["qty"] for s, p in positions.items())

    def record_equity(stamp, value, stage):
        nonlocal peak, max_dd
        peak = max(peak, value)
        dd = max(0.0, 1-value/peak) if peak > 0 else 1.0
        max_dd = max(max_dd, dd)
        equity_curve.append({"ts": stamp, "equity": value, "stage": stage})
        return dd

    def exit_position(symbol, trigger, stamp, reason):
        nonlocal cash, fees
        p = positions.pop(symbol)
        fill = trigger*(1-p["side"]*slip)
        charge = abs(fill*p["qty"])*fee_rate
        gross = p["side"]*(fill-p["entry"])*p["qty"]
        cash += gross-charge
        fees += charge
        trades.append({"symbol": symbol, "side": p["side"], "entry_ts": p["opened"],
                       "exit_observed_ts": stamp, "entry": p["entry"], "exit": fill,
                       "qty": p["qty"], "leverage": p["leverage"], "reason": reason,
                       "gross_pnl": gross, "fees": p["entry_fee"]+charge,
                       "funding_pnl": p["funding"],
                       "net_pnl": gross-p["entry_fee"]-charge+p["funding"]})
        last_exit[symbol] = stamp

    def apply_funding(symbol, bar, index, stopped=False):
        nonlocal cash, funding_total
        p = positions[symbol]
        events = rates[symbol]
        if events is None:
            # Explicit adverse estimate, for BOTH directions, at 8H boundaries.
            boundary = ((bar.ts//(8*HOUR_MS))+1)*(8*HOUR_MS)
            events_here = ([(boundary, config.funding_estimate_bps_per_8h/10000)]
                           if boundary <= bar.ts+HOUR_MS else [])
        else:
            left = bisect_right(rate_times[symbol], max(p["opened"], bar.ts))
            right = bisect_right(rate_times[symbol], bar.ts+HOUR_MS)
            events_here = events[left:right]
        for stamp, rate in events_here:
            # A native stop may precede an intrabar settlement. Unknown timing
            # is handled adversely: debit possible payments, omit possible
            # receipts, except a settlement exactly at close after a known stop.
            if stopped and stamp == bar.ts+HOUR_MS:
                continue
            if events is None:
                amount = -p["qty"]*bar.close*abs(rate)
            else:
                amount = -p["side"]*p["qty"]*bar.close*rate
            if stopped:
                amount = min(0.0, amount)
            cash += amount
            p["funding"] += amount
            funding_total += amount

    for index in range(start, end):
        stamp = timeline[index]
        bars = {s: streams[s][index] for s in symbols}
        opens = {s: bar.open for s, bar in bars.items()}
        dd = record_equity(stamp, equity(opens), "open")
        if dd >= config.max_drawdown and permanent_halt is None:
            permanent_halt = "max_drawdown"
        if permanent_halt:
            for symbol in list(positions):
                exit_position(symbol, opens[symbol], stamp, permanent_halt)
        if not permanent_halt and stamp >= pause_until:
            for symbol in sorted(pending):
                if symbol in positions:
                    continue
                decision = pending[symbol]
                entry = opens[symbol]*(1+decision.side*slip)
                spec = specs[symbol]
                tick = Decimal(str(spec.price_tick))
                # Match forward paper: preserve the causal ATR distance,
                # rebasing it around the actual next-open slipped entry.
                raw_stop = entry-decision.side*abs(decision.entry-decision.stop)
                stop = float((Decimal(str(raw_stop))/tick).to_integral_value(
                    rounding=ROUND_FLOOR if decision.side == 1 else ROUND_CEILING)*tick)
                if decision.side*(entry-stop) <= 0:
                    refused += 1
                    continue
                current_equity = equity(opens)
                sizing = size_position(current_equity, entry, stop, spec, config,
                    open_risk=sum(p["risk_cash"] for p in positions.values()),
                    used_margin=sum(p["margin"] for p in positions.values()),
                    gross_notional=sum(p["qty"]*opens[s] for s, p in positions.items()),
                    drawdown=max(0.0, 1-current_equity/peak))
                if sizing is None:
                    refused += 1
                    continue
                charge = sizing.notional*fee_rate
                cash -= charge
                fees += charge
                positions[symbol] = {"side": decision.side, "entry": entry, "stop": stop, "initial_stop": stop,
                    "qty": sizing.qty, "leverage": sizing.leverage, "margin": sizing.margin,
                    "risk_cash": sizing.risk_cash, "opened": stamp, "entry_fee": charge, "funding": 0.0}
        pending = {}
        # Gap/open orders and same-bar stops use only the stop active before
        # the bar; a newly calculated trailing stop cannot act retrospectively.
        adverse = dict(opens)
        stopped = {}
        for symbol, p in positions.items():
            bar = bars[symbol]
            hit = bar.low <= p["stop"] if p["side"] == 1 else bar.high >= p["stop"]
            trigger = min(bar.open, p["stop"]) if p["side"] == 1 else max(bar.open, p["stop"])
            stopped[symbol] = (hit, trigger)
            adverse[symbol] = trigger if hit else (bar.low if p["side"] == 1 else bar.high)
        worst_dd = record_equity(stamp, equity(adverse), "conservative_intrabar")
        # These simultaneous adverse marks are a conservative bound, not an
        # observed portfolio path; hourly candles cannot synchronize extremes.
        if worst_dd >= config.max_drawdown and permanent_halt is None:
            permanent_halt = "max_drawdown_intrabar_bound"
        for symbol in list(positions):
            bar = bars[symbol]
            hit, trigger = stopped[symbol]
            apply_funding(symbol, bar, index, stopped=hit)
            if hit:
                exit_position(symbol, trigger, stamp+HOUR_MS, "stop_intrabar_time_unknown")
            elif permanent_halt:
                exit_position(symbol, adverse[symbol], stamp+HOUR_MS, permanent_halt)
            elif stamp+HOUR_MS-positions[symbol]["opened"] >= config.max_hold_hours*HOUR_MS:
                exit_position(symbol, bar.close, stamp+HOUR_MS, "max_hold")
        closes = {s: bar.close for s, bar in bars.items()}
        close_equity = equity(closes)
        dd = record_equity(stamp+HOUR_MS, close_equity, "close")
        closed_equity_history.append((stamp+HOUR_MS, close_equity))
        threshold = stamp+HOUR_MS-24*HOUR_MS
        window = [row for row in closed_equity_history if row[0] >= threshold]
        # Rolling loss is measured against the earliest available 24H value.
        anchor = window[0][1] if window else config.initial_equity
        loss = max(0.0, 1-close_equity/anchor) if anchor > 0 else 1.0
        if dd >= config.max_drawdown or loss >= config.rolling_halt_loss:
            permanent_halt = permanent_halt or "rolling_loss_halt"
            for symbol in list(positions):
                exit_position(symbol, closes[symbol], stamp+HOUR_MS, permanent_halt)
        elif loss >= config.rolling_pause_loss:
            pause_until = max(pause_until, stamp+HOUR_MS+int(config.pause_hours*HOUR_MS))
        for symbol, p in positions.items():
            history = streams[symbol][max(0, index-config.history_limit+1):index+1]
            p["stop"] = policy.trailing_stop(symbol, p, history, config)
        for symbol, p in list(positions.items()):
            if policy.exit_signal(symbol, p, streams[symbol][max(0, index-config.history_limit+1):index+1], config):
                exit_position(symbol, closes[symbol], stamp+HOUR_MS, "strategy_exit")
        if not permanent_halt and stamp+HOUR_MS >= pause_until and index+1 < end:
            for symbol in symbols:
                if symbol in positions or stamp+HOUR_MS-last_exit.get(symbol, -10**18) < config.cooldown_bars*HOUR_MS:
                    continue
                history = streams[symbol][max(0, index-config.history_limit+1):index+1]
                decision = policy.evaluate(symbol, history, stamp+HOUR_MS, config)
                if decision:
                    pending[symbol] = decision
    ending_positions_before_close = [{"symbol": s, **p} for s, p in positions.items()]
    for symbol in list(positions):
        exit_position(symbol, streams[symbol][end-1].close, timeline[end-1]+HOUR_MS, "research_window_end")
    record_equity(timeline[end-1]+HOUR_MS, cash, "final_net_liquidation")
    wins = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    losses = -sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
    net = cash-config.initial_equity
    if not math.isclose(net, sum(t["net_pnl"] for t in trades), abs_tol=1e-7):
        raise AssertionError("cash and completed trade accounting disagree")
    return {"status": "RESEARCH_ONLY", "live_eligible": False,
            "strategy": config.strategy, "settings_fingerprint": config.fingerprint,
            "symbols": symbols, "start_ms": timeline[start], "end_ms": timeline[end-1]+HOUR_MS,
            "initial_stop_model": "signal ATR distance rebased to actual entry",
            "hours": end-start, "initial_equity": config.initial_equity, "final_equity": cash,
            "net_pnl": net, "return_fraction": net/config.initial_equity,
            "max_drawdown": max_dd, "drawdown_method": "open/close and conservative simultaneous intrabar adverse bound",
            "fees": fees, "funding_pnl": funding_total, "trade_count": len(trades),
            "profit_factor": wins/losses if losses else None,
            "profit_factor_state": "finite" if losses else "no_losses" if wins else "no_trades_or_pnl",
            "win_rate": sum(t["net_pnl"] > 0 for t in trades)/len(trades) if trades else None,
            "expectancy": net/len(trades) if trades else None,
            "refused_entries": refused, "halt": permanent_halt, "trades": trades,
            "equity_curve": equity_curve, "ending_positions_before_forced_close": ending_positions_before_close,
            "ending_positions": [], "funding_mode": {s: "provided_events_coverage_unverified" if rates[s] is not None else "ADVERSE_ESTIMATE_NOT_VALIDATED" for s in symbols},
            "assumed_instrument_symbols": guessed,
            "limitations": [
                "No order-book, partial fills, exchange liquidation tiers or actual intrabar event sequence.",
                "Trade-price OHLC approximates mark triggers; gap slippage can be worse in production.",
                "Funding events require separate coverage proof; absent streams use an adverse estimate.",
                "Intrabar funding uses hourly close price; stopped-bar ambiguous receipts are omitted.",
                "Intrabar portfolio extremes form a conservative simultaneous bound, not an observed path.",
                "Contract snapshots are current or explicitly assumed; historic rule changes are unmodeled.",
                "Infrastructure expense excluded. No candidate is eligible for automatic live promotion."]}


def backtest(candles, config, symbol="BTCUSDT", funding=None, *, instrument=None,
             start_index=None, end_index=None):
    return _simulate({symbol: list(candles)}, config,
                     {symbol: instrument} if instrument is not None else {},
                     {symbol: funding}, start_index, end_index)


def run_research(dataset, config, *, instruments=None, funding=None,
                 evaluate_holdout=False):
    """Compare fixed hypotheses on chronological development folds.

    Last 20% after common warmup remains sealed unless explicitly requested.
    Opting in evaluates ALL predeclared candidates; there is no automatic winner.
    Every fold resets capital and forces a terminal close, disclosed in output.
    """
    dataset = {symbol: list(rows) for symbol, rows in dataset.items()}
    if not dataset:
        raise ValueError("no dataset")
    count = len(next(iter(dataset.values())))
    common_warmup = max(_warmup(_candidate(config, name)) for name in CANDIDATES)
    split = common_warmup + int((count-common_warmup)*.8)
    if split-common_warmup < 9 or split >= count:
        raise ValueError("insufficient research and holdout observations")
    folds = [(common_warmup+(split-common_warmup)*i//3,
              common_warmup+(split-common_warmup)*(i+1)//3) for i in range(3)]
    results = []
    for name in CANDIDATES:
        candidate = _candidate(config, name)
        for cost_multiple in (1, 2):
            stressed = replace(candidate, fee_bps=config.fee_bps*cost_multiple,
                               slippage_bps=config.slippage_bps*cost_multiple)
            for number, (left, right) in enumerate(folds, 1):
                result = _simulate(dataset, stressed, instruments, funding, left, right)
                results.append({"candidate": name, "cost_multiplier": cost_multiple,
                                "fold": number, **result})
    holdout = []
    if evaluate_holdout:
        for name in CANDIDATES:
            holdout.append({"candidate": name, **_simulate(dataset, _candidate(config, name),
                            instruments, funding, split, count)})
    timeline = next(iter(dataset.values()))
    return {"schema": 1, "status": "RESEARCH_ONLY", "live_eligible": False,
            "comparison": "fixed candidates; no fitting, selection or automatic promotion",
            "portfolio": "shared cash; aggregate correlated risk, margin and gross caps; alphabetical simultaneous entry order",
            "capital_policy": "fresh initial capital each fold; terminal positions closed at fold end",
            "cost_stress": "fees/slippage doubled before sizing, so sizes and trade sets may differ",
            "common_warmup_hours": common_warmup,
            "adequate_window_length": all(right-left >= 720 for left, right in folds),
            "holdout": {"start_ms": timeline[split].ts, "end_ms": timeline[-1].ts+HOUR_MS,
                        "evaluated": evaluate_holdout, "results": holdout},
            "results": results,
            "promotion_blockers": ["independent long-window OOS", "funding and mark-data coverage",
                                   "measured execution costs", "exchange demo recovery", "forward paper evidence"]}

def run_v2_research():
    import json
    from pathlib import Path
    from src.bitget_bot.config import load_settings
    from src.bitget_bot.models import Candle
    
    cfg = load_settings("config/paper.toml")
    raw = json.loads(Path("artifacts/history_180d_20260923.json").read_text(encoding="utf-8"))
    dataset = {s: [Candle(**c) for c in rows] for s, rows in raw["symbols"].items()}
    book = FeatureBook(dataset)
    
    common_warmup = 300
    count = len(next(iter(dataset.values())))
    split = common_warmup + int((count-common_warmup)*.8)
    folds = [(common_warmup+(split-common_warmup)*i//3,
              common_warmup+(split-common_warmup)*(i+1)//3) for i in range(3)]
              
    results = []
    for name in NAMES:
        if name == "baseline_breakout24": continue
        print(f"Testing {name}...")
        cand_cfg = candidate(name, cfg)
        pol = Policy(name, book)
        
        # Test on cost_multiple = 1 only for speed
        for number, (left, right) in enumerate(folds, 1):
            result = _simulate(dataset, cand_cfg.settings, None, None, left, right, policy=pol)
            results.append({
                "candidate": name,
                "fold": number,
                "net_pnl": result["net_pnl"],
                "profit_factor": result["profit_factor"],
                "trade_count": result["trade_count"],
                "max_drawdown": result["max_drawdown"]
            })
            print(f"  Fold {number}: {result['net_pnl']:.2f} PnL, {result['trade_count']} trades, PF {result['profit_factor']}")

if __name__ == '__main__':
    run_v2_research()
