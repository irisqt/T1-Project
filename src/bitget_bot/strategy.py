"""Causal, closed-hour research hypotheses, not a validated profit forecast."""
from __future__ import annotations

import math
from .models import Candle, Signal

HOUR_MS = 3_600_000


def _valid(candles, interval=HOUR_MS):
    if not candles:
        return False
    for i, bar in enumerate(candles):
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if (not isinstance(bar.ts, int) or bar.ts < 0 or bar.ts % interval
                or not all(math.isfinite(x) for x in values)
                or min(values[:4]) <= 0 or bar.volume < 0
                or bar.high < max(bar.open, bar.close)
                or bar.low > min(bar.open, bar.close)):
            return False
        if i and bar.ts - candles[i-1].ts != interval:
            return False
    return True


def ema(values, period):
    """SMA-seeded EMA; callers supply only information available at decision."""
    if period < 2 or len(values) < period:
        raise ValueError("insufficient EMA history")
    result = sum(values[:period]) / period
    weight = 2 / (period + 1)
    for value in values[period:]:
        result += weight * (value - result)
    return result


def atr(candles, period=14):
    if period < 2 or len(candles) < period + 1:
        raise ValueError("insufficient ATR history")
    rows = candles[-period-1:]
    return sum(max(cur.high-cur.low, abs(cur.high-prev.close),
                   abs(cur.low-prev.close)) for prev, cur in zip(rows, rows[1:])) / period


def evaluate(symbol, candles, now_ms, config):
    """Return one fresh signal using completed bars only.

    V2 hypothesis: Donchian breakout with EMA direction/slope, or a separately
    declared 48-hour momentum alternative. Neither is the reference EMA200/4H
    baseline. A late historical signal is deliberately not traded.
    """
    interval = config.candle_interval_ms
    closed = [bar for bar in candles if bar.ts + interval <= now_ms]
    need = max(config.ema_period + config.slope_bars, config.atr_period + 1,
               config.breakout_bars + 1, config.momentum_bars + 1)
    if len(closed) < need or not _valid(closed, interval):
        return None
    latest = closed[-1]
    age = now_ms - latest.ts - interval
    if age < 0 or age > config.max_signal_age_ms:
        return None
    volatility = atr(closed, config.atr_period)
    if not math.isfinite(volatility) or volatility <= 0 or volatility/latest.close > config.max_atr_fraction:
        return None
    closes = [bar.close for bar in closed]
    trend = ema(closes, config.ema_period)
    old_trend = ema(closes[:-config.slope_bars], config.ema_period)
    if config.strategy == "breakout":
        channel = closed[-config.breakout_bars-1:-1]
        side = (1 if latest.close > max(bar.high for bar in channel)
                else -1 if latest.close < min(bar.low for bar in channel) else 0)
        reason = f"donchian_{config.breakout_bars}_ema{config.ema_period}_slope{config.slope_bars}"
    elif config.strategy == "momentum":
        change = latest.close - closed[-config.momentum_bars-1].close
        side = 1 if change > volatility else -1 if change < -volatility else 0
        reason = f"momentum_{config.momentum_bars}_atr_threshold_ema{config.ema_period}"
    else:
        return None
    if not side or side*(latest.close-trend) <= 0 or side*(trend-old_trend) <= 0:
        return None
    stop = latest.close - side*config.atr_multiplier*volatility
    if stop <= 0:
        return None
    return Signal(symbol, side, latest.ts, latest.close, stop, reason)


def trailing_stop(side, old_stop, candles, config=None):
    """Use the preceding channel (exclude newest bar); never loosen a stop.

    Call after a completed bar and activate the result on the next interval.
    All supplied bars must already be completed. config is optional for the
    engine's simple three-argument interface.
    """
    period = config.trailing_bars if config is not None else 12
    if side not in (-1, 1) or not math.isfinite(old_stop) or old_stop <= 0:
        raise ValueError("invalid protective stop")
    if len(candles) < period + 1:
        return old_stop
    if not _valid(candles):
        raise ValueError("invalid trailing history")
    history = candles[-period-1:-1]
    boundary = min(bar.low for bar in history) if side == 1 else max(bar.high for bar in history)
    return max(old_stop, boundary) if side == 1 else min(old_stop, boundary)
