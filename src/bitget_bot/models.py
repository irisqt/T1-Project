from dataclasses import dataclass

@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

@dataclass(frozen=True)
class Instrument:
    symbol: str
    qty_step: float
    min_qty: float
    min_notional: float
    price_tick: float
    max_leverage: int = 30
    maintenance_margin: float = .01
    status: str = "online"

@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    mark: float
    index: float
    ts: int
    received_ts: int
    funding_rate: float = 0.0
    next_funding_ts: int = 0

@dataclass(frozen=True)
class Funding:
    ts: int
    rate: float

@dataclass(frozen=True)
class Signal:
    symbol: str
    side: int
    ts: int
    entry: float
    stop: float
    reason: str

@dataclass(frozen=True)
class Sizing:
    qty: float
    leverage: int
    notional: float
    margin: float
    risk_cash: float
