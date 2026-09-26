"""Finite, preregistered causal strategy hypotheses; no automatic deployment.

The same policy methods can be used by a forward observer. Feature construction
does not use future candles; a partial UTC four-hour group is never a signal.
"""
from dataclasses import dataclass, replace
from statistics import pstdev

from .models import Candle, Signal
from .strategy import _valid, atr, ema

HOUR = 3_600_000
NAMES = ("baseline_breakout24", "trend4h_20", "trend4h_40", "pullback4h",
         "range1h", "range4h")
BASE_ROUND_TRIP_COST = .002  # fixed signal hurdle, even in execution stress


def aggregate_four_hours(candles):
    """All input bars must be complete; skip incomplete edge groups, reject gaps."""
    if not _valid(candles):
        raise ValueError("four-hour aggregation requires consecutive valid hours")
    result = []
    group = []
    for bar in candles:
        if bar.ts % (4 * HOUR) == 0:
            group = [bar]
        elif group:
            group.append(bar)
        if len(group) == 4:
            result.append(Candle(group[0].ts, group[0].open,
                                max(x.high for x in group), min(x.low for x in group),
                                group[-1].close, sum(x.volume for x in group)))
            group = []
    return result


def _features(rows, band_period, interval):
    if len(rows) < 103:
        return None
    history = rows[-200:]
    closes = [bar.close for bar in history]
    changes = [abs(b-a) for a, b in zip(closes[-25:-1], closes[-24:])]
    total = sum(changes)
    efficiency = abs(closes[-1]-closes[-25])/total if total else 0.0
    recent = closes[-band_period:]
    mean = sum(recent)/band_period
    sigma = pstdev(recent)
    previous = closes[-band_period-1:-1]
    previous_mean = sum(previous)/band_period
    previous_sigma = pstdev(previous)
    return {
        "end_ms": history[-1].ts+interval, "close": closes[-1],
        "previous_close": closes[-2], "atr": atr(history, 14),
        "slow": ema(closes, 100), "old_slow": ema(closes[:-3], 100),
        "fast": ema(closes, 20), "old_fast": ema(closes[:-1], 20),
        "efficiency": efficiency, "mean": mean,
        "z": (closes[-1]-mean)/sigma if sigma else 0.0,
        "previous_z": (closes[-2]-previous_mean)/previous_sigma if previous_sigma else 0.0,
        "high20": max(b.high for b in history[-21:-1]),
        "low20": min(b.low for b in history[-21:-1]),
        "high40": max(b.high for b in history[-41:-1]),
        "low40": min(b.low for b in history[-41:-1]),
        "trail_high": max(b.high for b in history[-12:]),
        "trail_low": min(b.low for b in history[-12:]),
    }


class FeatureBook:
    """Reusable prefix-only features indexed by the last complete hourly bar."""

    def __init__(self, dataset):
        self.data = {}
        for symbol, rows in dataset.items():
            if not _valid(rows):
                raise ValueError("feature book requires contiguous complete hours")
            four = aggregate_four_hours(rows)
            four_by_end = {bar.ts+4*HOUR: bar for bar in four}
            four_history = []
            hourly_history = []
            latest_four = None
            frames = {}
            for bar in rows:
                hourly_history.append(bar)
                hourly_history = hourly_history[-200:]
                if bar.ts+HOUR in four_by_end:
                    four_history.append(four_by_end[bar.ts+HOUR])
                    four_history = four_history[-200:]
                    latest_four = _features(four_history, 24, 4*HOUR)
                frames[bar.ts] = {"one": _features(hourly_history, 48, HOUR),
                                  "four": latest_four}
            self.data[symbol] = frames

    def at(self, symbol, history):
        if not history:
            return {"one": None, "four": None}
        return self.data.get(symbol, {}).get(history[-1].ts,
                                             {"one": None, "four": None})


@dataclass(frozen=True)
class Candidate:
    name: str
    settings: object


def candidate(name, base):
    if name not in NAMES:
        raise ValueError("candidate was not preregistered")
    if name == "baseline_breakout24":
        return Candidate(name, replace(base, strategy="breakout", breakout_bars=24))
    trend = name.startswith("trend") or name == "pullback4h"
    hold = 168.0 if trend else 24.0 if name == "range1h" else 72.0
    settings = replace(base, strategy="breakout", history_limit=1000,
                       atr_multiplier=2.5 if trend else 2.0,
                       max_hold_hours=hold, cooldown_bars=8)
    return Candidate(name, settings.validate())


class Policy:
    def __init__(self, name, book):
        if name not in NAMES or name == "baseline_breakout24":
            raise ValueError("use original policy for baseline")
        self.name = name
        self.book = book

    def evaluate(self, symbol, history, now, config):
        if not history:
            return None
        boundary = history[-1].ts+HOUR
        if not 0 <= now-boundary <= config.max_signal_age_ms:
            return None
        frames = self.book.at(symbol, history)
        four = frames["four"]
        frame = frames["one"] if self.name == "range1h" else four
        if not four or not frame or (self.name != "range1h" and four["end_ms"] != boundary):
            return None
        price, volatility = frame["close"], frame["atr"]
        if volatility <= 0 or volatility/price > config.max_atr_fraction:
            return None
        side = 0
        if self.name.startswith("trend") or self.name == "pullback4h":
            if four["efficiency"] < .25:
                return None
            direction = (1 if four["close"] > four["slow"] > four["old_slow"]
                         else -1 if four["close"] < four["slow"] < four["old_slow"] else 0)
            if self.name.startswith("trend"):
                lookback = "20" if self.name == "trend4h_20" else "40"
                side = (1 if price > frame["high"+lookback]
                        else -1 if price < frame["low"+lookback] else 0)
            elif (direction == 1 and four["fast"] > four["slow"]
                  and four["previous_close"] <= four["old_fast"] and price > four["fast"]):
                side = 1
            elif (direction == -1 and four["fast"] < four["slow"]
                  and four["previous_close"] >= four["old_fast"] and price < four["fast"]):
                side = -1
            if side != direction:
                return None
        else:
            if (four["efficiency"] > .25
                    or abs(four["slow"]-four["old_slow"]) > .3*four["atr"]):
                return None
            side = (1 if frame["previous_z"] <= -2 and -2 < frame["z"] < 0
                    else -1 if frame["previous_z"] >= 2 and 0 < frame["z"] < 2 else 0)
        if not side:
            return None
        distance = config.atr_multiplier*volatility
        if distance/price < 4*BASE_ROUND_TRIP_COST:
            return None
        if self.name.startswith("range"):
            target_distance = side*(frame["mean"]-price)
            if target_distance < max(distance, price*4*BASE_ROUND_TRIP_COST):
                return None
        stop = price-side*distance
        if stop <= 0:
            return None
        return Signal(symbol, side, history[-1].ts, price, stop, self.name)

    def trailing_stop(self, symbol, position, history, config):
        old_stop = position["stop"]
        if self.name.startswith("range"):
            return old_stop
        frame = self.book.at(symbol, history)["four"]
        if frame is None:
            return old_stop
        side, entry = position["side"], position["entry"]
        initial_risk = abs(entry-position["initial_stop"])
        if side*(frame["close"]-entry) < initial_risk:
            return old_stop
        level = frame["trail_high"]-3*frame["atr"] if side == 1 else frame["trail_low"]+3*frame["atr"]
        return max(old_stop, level) if side == 1 else min(old_stop, level)

    def exit_signal(self, symbol, position, history, config):
        if not self.name.startswith("range") or not history:
            return False
        frames = self.book.at(symbol, history)
        frame = frames["one"] if self.name == "range1h" else frames["four"]
        if frame is None or frame["end_ms"] != history[-1].ts+HOUR:
            return False
        return position["side"]*(frame["close"]-frame["mean"]) >= 0
