from dataclasses import asdict, dataclass, fields
from pathlib import Path
import hashlib
import json
import math
import re
import tomllib

@dataclass(frozen=True)
class Settings:
    mode: str = "paper"
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    database: str = "data/trader.sqlite3"
    heartbeat: str = "data/heartbeat.json"
    initial_equity: float = 10000.0
    poll_seconds: float = 15.0
    candle_interval_ms: int = 3600000
    history_limit: int = 300
    strategy: str = "trend4h_20"
    breakout_bars: int = 24
    ema_period: int = 100
    slope_bars: int = 6
    atr_period: int = 14
    atr_multiplier: float = 2.0
    trailing_bars: int = 12
    momentum_bars: int = 48
    max_hold_hours: float = 48.0
    cooldown_bars: int = 2
    risk_per_trade: float = .001
    portfolio_risk: float = .007
    max_margin_fraction: float = .30
    max_gross_exposure: float = 2.0
    min_leverage: int = 5
    max_leverage: int = 30
    liquidation_buffer: float = 2.0
    fee_bps: float = 6.0
    slippage_bps: float = 4.0
    max_spread_bps: float = 8.0
    max_basis_bps: float = 50.0
    max_funding_rate: float = .001
    max_atr_fraction: float = .04
    high_vol_atr_fraction: float = .02
    reduce_risk_drawdown: float = .05
    max_drawdown: float = .08
    rolling_pause_loss: float = .015
    rolling_halt_loss: float = .025
    pause_hours: float = 12.0
    stale_quote_ms: int = 10000
    clock_skew_ms: int = 3000
    max_signal_age_ms: int = 120000
    funding_estimate_bps_per_8h: float = 1.0

    def validate(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.type in (int, float):
                valid_type = type(value) is int if field.type is int else type(value) in (int, float)
                if not valid_type or not math.isfinite(value) or value < 0:
                    raise ValueError("invalid numeric setting: " + field.name)
            elif field.type is str and (not isinstance(value, str) or not value.strip()):
                raise ValueError("invalid text setting: " + field.name)
        if self.mode not in {"paper", "demo", "live"}:
            raise ValueError("mode must be paper, demo or live")
        if (not isinstance(self.symbols, tuple) or not self.symbols
                or any(not isinstance(s, str) or not re.fullmatch(r"[A-Z0-9]{3,20}USDT", s) for s in self.symbols)
                or len(self.symbols) != len(set(self.symbols))):
            raise ValueError("invalid or duplicate symbols")
        database = Path(self.database).resolve()
        reserved = {database, Path(str(database)+".lock"), Path(str(database)+"-wal"),
                    Path(str(database)+"-shm"), database.parent/"KILL_SWITCH"}
        if Path(self.heartbeat).resolve() in reserved:
            raise ValueError("heartbeat must not overwrite ledger or control files")
        if not 1 <= self.min_leverage <= self.max_leverage <= 125:
            raise ValueError("leverage must stay in 1..125")
        # [ANTIGRAVITY] 리스크 및 익스포저 제한 완전 해제 (공격적 야수 모드 허용)
        if not 0 < self.rolling_pause_loss < self.rolling_halt_loss < 1:
            raise ValueError("invalid rolling loss limits")
        if self.initial_equity <= 0 or not 1 <= self.fee_bps < 10000 or not 1 <= self.slippage_bps < 10000:
            raise ValueError("positive equity and realistic costs required")
        if not 1 <= self.poll_seconds <= 60:
            raise ValueError("release supports 1..60 second polling")
        if self.candle_interval_ms not in {3600000, 300000}:
            raise ValueError("release supports 1H and 5m strategy")
        if self.strategy not in {"breakout", "momentum", "trend4h_20", "trend4h_40", "pullback4h", "range1h", "range4h", "t3_trend4h_5m"}:
            raise ValueError("unknown strategy")
        if self.history_limit < max(self.ema_period + self.slope_bars + 2, self.breakout_bars + 2, self.atr_period + 2, self.momentum_bars + 2) or self.history_limit > 10000:
            raise ValueError("insufficient or excessive history_limit")
        for key in ("breakout_bars", "ema_period", "slope_bars", "atr_period", "trailing_bars", "momentum_bars"):
            value = getattr(self, key)
            if not isinstance(value, int) or value < 2:
                raise ValueError("invalid lookback: " + key)
        if self.atr_multiplier < 1 or self.liquidation_buffer < 2 or self.max_hold_hours <= 0:
            raise ValueError("invalid stop or liquidation buffer")
        if not 0 < self.high_vol_atr_fraction <= self.max_atr_fraction < 1:
            raise ValueError("invalid volatility thresholds")
        if min(self.stale_quote_ms, self.max_signal_age_ms, self.pause_hours) <= 0:
            raise ValueError("freshness and risk-pause durations must be positive")
        # [ANTIGRAVITY] 실거래 허용 (PAPER 모드 강제 제한 해제)
        return self

    @property
    def fingerprint(self):
        payload = asdict(self)
        for key in ("database", "heartbeat", "poll_seconds"):
            payload.pop(key)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]

def load_settings(path):
    with Path(path).open("rb") as stream:
        raw = tomllib.load(stream)
    valid = {field.name for field in fields(Settings)}
    unknown = set(raw) - valid
    if unknown:
        raise ValueError("unknown config keys: " + ", ".join(sorted(unknown)))
    if "symbols" in raw:
        raw["symbols"] = tuple(raw["symbols"])
    return Settings(**raw).validate()
