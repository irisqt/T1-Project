from dataclasses import dataclass, replace
from statistics import pstdev

from .models import Candle, Signal
from .strategy import _valid, atr, ema

MINUTE = 60_000
INTERVAL = 5 * MINUTE
HOUR = 60 * MINUTE
NAMES = ("t3_trend4h_5m",)
BASE_ROUND_TRIP_COST = .002

def aggregate_candles(candles, target_interval_ms):
    """Aggregate 5m candles into larger timeframes like 4H or 1H."""
    if not candles:
        return []
    result = []
    group = []
    for bar in candles:
        if bar.ts % target_interval_ms == 0:
            if group:
                result.append(Candle(group[0].ts, group[0].open,
                                    max(x.high for x in group), min(x.low for x in group),
                                    group[-1].close, sum(x.volume for x in group)))
            group = [bar]
        elif group:
            group.append(bar)
            
    # Include the last incomplete group so the "current" higher timeframe bar is available
    if group:
        result.append(Candle(group[0].ts, group[0].open,
                            max(x.high for x in group), min(x.low for x in group),
                            group[-1].close, sum(x.volume for x in group)))
    return result

def _features(rows, band_period, interval):
    if len(rows) < 45:
        return None
    history = rows[-100:]
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
        "end_ms": history[-1].ts + interval, "close": closes[-1],
        "previous_close": closes[-2], "atr": atr(history, 14),
        "slow": ema(closes, 40), "old_slow": ema(closes[:-3], 40),
        "fast": ema(closes, 10), "old_fast": ema(closes[:-1], 10),
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
    """Computes features for the Mothership (4H) and Action (5m) timeframes."""
    def __init__(self, dataset):
        self.data = {}
        for symbol, rows in dataset.items():
            if not _valid(rows, INTERVAL):
                raise ValueError("feature book requires contiguous complete 5m candles")
                
            frames = {}
            for i in range(200, len(rows)):
                # We need to look back enough to compute 4H EMAs (e.g. 100 * 4H = 400 hours = 4800 5m bars)
                # To save time, we will just pass a slice.
                # In real life we'd incrementally compute.
                pass
            
            self.data[symbol] = frames

    def at(self, symbol, history):
        # Dynamically compute features on the fly for backtesting to save memory
        if not history or len(history) < 200:
            return {"action": None, "mothership": None}
            
        action = _features(history[-200:], 24, INTERVAL)
        
        # Aggregate 5m history into 4H candles (Mothership)
        recent_history = history[-4000:] if len(history) >= 4000 else history
        mothership_candles = aggregate_candles(recent_history, 4 * HOUR)
        mothership = _features(mothership_candles, 20, 4 * HOUR) if len(mothership_candles) >= 45 else None
        
        return {"action": action, "mothership": mothership}

@dataclass(frozen=True)
class Candidate:
    name: str
    settings: object

def candidate(name, base):
    if name not in NAMES:
        raise ValueError("candidate was not preregistered")
    
    settings = replace(base, strategy="breakout", history_limit=8000,
                       atr_multiplier=2.5,
                       max_hold_hours=168.0, cooldown_bars=8)
    return Candidate(name, settings.validate())

class Policy:
    def __init__(self, name, book):
        self.name = name
        self.book = book

    def evaluate(self, symbol, history, now, config):
        if not history:
            return None
        boundary = history[-1].ts + INTERVAL
        if not 0 <= now - boundary <= config.max_signal_age_ms:
            return None
            
        frames = self.book.at(symbol, history)
        ms = frames["mothership"]
        action = frames["action"]
        
        if not ms or not action:
            return None
            
        # MOTHERSHIP (4H) Trend Filter
        if ms["efficiency"] < .25:
            return None
            
        direction = (1 if ms["close"] > ms["fast"] > ms["slow"] > ms["old_slow"]
                     else -1 if ms["close"] < ms["fast"] < ms["slow"] < ms["old_slow"] else 0)
                     
        if direction == 0:
            return None

        # ACTION (5m) Trigger
        # E.g., Breakout of 20-bar high on 5m timeframe, in the direction of 4H trend
        side = 0
        price = action["close"]
        volatility = action["atr"]
        
        if direction == 1 and price > action["high40"]:
            side = 1
        elif direction == -1 and price < action["low40"]:
            side = -1
            
        if side != direction or side == 0:
            return None
            
        distance = config.atr_multiplier * volatility
        if distance / price < 4 * BASE_ROUND_TRIP_COST:
            return None
            
        stop = price - side * distance
        if stop <= 0:
            return None
            
        return Signal(symbol, side, history[-1].ts, price, stop, self.name)

    def trailing_stop(self, symbol, position, history, config):
        old_stop = position["stop"]
        frames = self.book.at(symbol, history)
        action = frames["action"]
        if action is None:
            return old_stop
            
        side, entry = position["side"], position["entry"]
        initial_risk = abs(entry - position["initial_stop"])
        if side * (action["close"] - entry) < initial_risk:
            return old_stop
            
        level = action["trail_high"] - 2.5 * action["atr"] if side == 1 else action["trail_low"] + 2.5 * action["atr"]
        return max(old_stop, level) if side == 1 else min(old_stop, level)

    def exit_signal(self, symbol, position, history, config):
        return False
