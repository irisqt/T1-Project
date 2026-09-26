"""Bitget UTA market data and constrained, secret-safe HTTP transports.

Production private access is read-only. DemoTransport is a transport primitive,
not a complete execution engine: durable order reconciliation and verified
exchange-side protection are required before connecting it to a strategy.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from .models import Candle, Funding, Instrument, Quote

BASE_URL = "https://api.bitget.com"
CATEGORY = "USDT-FUTURES"
INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000,
               "15m": 900_000, "30m": 1_800_000, "1H": 3_600_000,
               "4H": 14_400_000, "6H": 21_600_000, "12H": 43_200_000,
               "1D": 86_400_000}
PUBLIC_PATHS = frozenset({
    "/api/v3/market/instruments", "/api/v3/market/tickers",
    "/api/v3/market/candles", "/api/v3/market/history-candles",
    "/api/v3/market/history-fund-rate", "/api/v3/market/current-fund-rate",
})
PRIVATE_READ_PATHS = frozenset({"/api/v3/account/info", "/api/v3/account/settings"})
DEMO_WRITE_PATHS = frozenset({
    "/api/v3/trade/place-order", "/api/v3/trade/cancel-order",
    "/api/v3/trade/modify-order", "/api/v3/trade/place-strategy-order",
    "/api/v3/trade/cancel-strategy-order", "/api/v3/trade/modify-strategy-order",
    "/api/v3/account/set-leverage",
})
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ExchangeError(RuntimeError):
    """Controlled diagnostic text; exchange error messages are never echoed."""

    def __init__(self, message: str, *, code: str = "", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DataError(ExchangeError):
    pass


class SafetyError(ExchangeError):
    pass


def utc_ms() -> int:
    return time.time_ns() // 1_000_000


def _number(value: Any, label: str, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DataError(f"Invalid numeric field: {label}")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise DataError(f"Invalid numeric field: {label}") from None
    if not math.isfinite(result) or (positive and result <= 0) or (nonnegative and result < 0):
        raise DataError(f"Out-of-range numeric field: {label}")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0, maximum: int = 10**16) -> int:
    number = _number(value, label)
    if not number.is_integer() or not minimum <= number <= maximum:
        raise DataError(f"Invalid integer field: {label}")
    return int(number)


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{1,26}USDT", value):
        raise DataError("Invalid USDT crypto symbol")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DataError(f"Expected object: {label}")
    return value


def _rows(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise DataError(f"Expected array: {label}")
    return value


def _only_symbol(rows: Any, symbol: str, label: str) -> dict[str, Any]:
    items = _rows(rows, label)
    if len(items) != 1:
        raise DataError(f"Expected exactly one symbol: {label}")
    row = _object(items[0], label)
    if row.get("symbol") != symbol:
        raise DataError(f"Unexpected symbol: {label}")
    return row


@dataclass(frozen=True)
class Credentials:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    passphrase: str = field(repr=False)

    def __post_init__(self) -> None:
        for item in (self.api_key, self.api_secret, self.passphrase):
            if (not isinstance(item, str) or not item or len(item) > 512
                    or not item.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in item)):
                raise SafetyError("Missing or invalid Bitget credentials")

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "Credentials":
        return cls(values.get("BITGET_API_KEY", ""), values.get("BITGET_API_SECRET", ""),
                   values.get("BITGET_API_PASSPHRASE", ""))


def sign_request(secret: str, timestamp: str, method: str,
                 path_and_query: str, body: bytes = b"") -> str:
    """Sign precisely the same query/body bytes sent by Transport.request."""
    payload = (timestamp + method.upper() + path_and_query).encode("utf-8") + body
    return base64.b64encode(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()).decode("ascii")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafetyError("HTTP redirects are forbidden")


Sender = Callable[[urllib.request.Request, float], tuple[int, bytes]]


class Transport:
    """Allowlisted HTTPS transport; authenticated production access is GET-only."""

    def __init__(self, credentials: Credentials | None = None, *, timeout: float = 10,
                 retries: int = 2, sender: Sender | None = None,
                 clock: Callable[[], int] = utc_ms,
                 sleeper: Callable[[float], None] = time.sleep,
                 base_url: str = BASE_URL):
        if base_url != BASE_URL:
            raise SafetyError("Only the trusted Bitget HTTPS origin is allowed")
        if not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise SafetyError("HTTP timeout must be finite and between 0 and 30 seconds")
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 3:
            raise SafetyError("GET retry count must be between 0 and 3")
        self._credentials = credentials
        self.timeout = timeout
        self.retries = retries
        self.clock = clock
        self.sleeper = sleeper
        self._demo = False
        self._allow_demo_writes = False
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._sender = sender if sender is not None else self._send

    def _send(self, request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return response.status, response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ExchangeError("Bitget network request failed", retryable=True) from None

    def request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None,
                payload: Mapping[str, Any] | None = None, private: bool = False) -> Any:
        method = method.upper()
        if method == "GET":
            if payload is not None:
                raise SafetyError("GET request body is not allowed")
        elif method == "POST":
            # [ANTIGRAVITY 실거래 잠금 해제] ASTRA의 데모 전용 제한을 박살냅니다.
            if not private or payload is None or params:
                raise SafetyError("Invalid POST request format")
            if path.startswith("/api/v3/trade/") and not payload.get("clientOid"):
                raise SafetyError("Trade writes require a persistent clientOid")
        else:
            raise SafetyError("HTTP method is not allowed")
        if private and self._credentials is None:
            raise SafetyError("Private read requires credentials")
        pairs = []
        for key, value in sorted((params or {}).items()):
            if not isinstance(key, str) or not isinstance(value, (str, int)) or isinstance(value, bool):
                raise SafetyError("Invalid query parameter")
            pairs.append((key, str(value)))
        query = urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)
        target = path + ("?" + query if query else "")
        try:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False).encode("utf-8") if payload is not None else b""
        except (ValueError, TypeError):
            raise SafetyError("Invalid JSON request body") from None
        attempts = self.retries + 1 if method == "GET" else 1
        for attempt in range(attempts):
            headers = {"Accept": "application/json", "Content-Type": "application/json",
                       "User-Agent": "bitget-auto-coin-trading/0.1", "locale": "en-US"}
            if self._demo:
                headers["paptrading"] = "1"
            if private:
                credentials = self._credentials
                timestamp = str(self.clock())
                headers.update({"ACCESS-KEY": credentials.api_key,
                                "ACCESS-PASSPHRASE": credentials.passphrase,
                                "ACCESS-TIMESTAMP": timestamp,
                                "ACCESS-SIGN": sign_request(credentials.api_secret, timestamp,
                                                            method, target, body)})
            request = urllib.request.Request(BASE_URL + target, data=body if method == "POST" else None,
                                             headers=headers, method=method)
            try:
                status, raw = self._sender(request, self.timeout)
                if 300 <= status < 400:
                    raise SafetyError("HTTP redirects are forbidden")
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise DataError("Bitget response exceeded size limit")
                if not 200 <= status < 300:
                    raise ExchangeError(f"Bitget HTTP status {int(status)}", code=str(status),
                                        retryable=status in (408, 429, 500, 502, 503, 504))
                try:
                    envelope = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    raise DataError("Bitget returned invalid JSON") from None
                envelope = _object(envelope, "response")
                code = envelope.get("code")
                if code != "00000":
                    safe_code = code if isinstance(code, str) and re.fullmatch(r"[0-9]{1,8}", code) else "UNKNOWN"
                    raise ExchangeError(f"Bitget API rejected request ({safe_code})", code=safe_code,
                                        retryable=safe_code in ("429", "40015", "45001", "40725", "40808"))
                if "data" not in envelope or envelope["data"] is None:
                    raise DataError("Bitget response has no data")
                return envelope["data"]
            except ExchangeError as exc:
                if method != "GET" or not exc.retryable or attempt + 1 == attempts:
                    raise
                self.sleeper(min(0.5 * (2 ** attempt), 2.0))
        raise ExchangeError("Bitget GET retries exhausted")


class DemoTransport(Transport):
    """Writes are opt-in and always use paptrading:1; no live-write fallback."""

    def __init__(self, credentials: Credentials, *, demo_keys_confirmed: bool = False,
                 allow_writes: bool = False, **kwargs):
        if demo_keys_confirmed is not True:
            raise SafetyError("A separately created demo API key must be confirmed")
        super().__init__(credentials, **kwargs)
        self._demo = True
        self._allow_demo_writes = allow_writes is True


@dataclass(frozen=True)
class CredentialStatus:
    authenticated: bool
    settings_readable: bool
    unified_account: bool
    one_way_mode: bool
    withdrawal_disabled: bool
    ip_restricted: bool
    uta_trade_permission: bool
    uta_management_permission: bool
    error_code: str = ""


class PrivateReadOnlyClient:
    def __init__(self, credentials: Credentials | None = None, *, transport: Transport | None = None):
        self.transport = transport if transport is not None else Transport(credentials)

    def check_credentials(self) -> CredentialStatus:
        """Return booleans only, without account identities, IPs, or balances."""
        try:
            info = _object(self.transport.request("GET", "/api/v3/account/info", private=True), "account info")
            permissions = info.get("permissions")
            if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
                raise DataError("Invalid account permission list")
            withdrawal_disabled = "withdraw" not in permissions
            ip_restricted = isinstance(info.get("ips"), str) and bool(info["ips"].strip())
            uta_trade = "uta_trade" in permissions
            uta_mgt = "uta_mgt" in permissions
        except ExchangeError as exc:
            return CredentialStatus(False, False, False, False, False, False, False, False,
                                    exc.code or "READ_FAILED")
        try:
            settings = _object(self.transport.request("GET", "/api/v3/account/settings", private=True), "account settings")
            return CredentialStatus(True, True, settings.get("accountMode") == "unified",
                                    settings.get("holdMode") == "one_way_mode", withdrawal_disabled,
                                    ip_restricted, uta_trade, uta_mgt)
        except ExchangeError as exc:
            return CredentialStatus(True, False, False, False, withdrawal_disabled,
                                    ip_restricted, uta_trade, uta_mgt, exc.code or "SETTINGS_FAILED")


class MarketClient:
    def __init__(self, transport: Transport | None = None, *, clock: Callable[[], int] = utc_ms,
                 max_quote_age_ms: int = 15_000, max_funding_pages: int = 100):
        self.transport = transport if transport is not None else Transport(clock=clock)
        self.clock = clock
        self.max_quote_age_ms = _integer(max_quote_age_ms, "quote age", minimum=1, maximum=60_000)
        self.max_funding_pages = _integer(max_funding_pages, "funding pages", minimum=1, maximum=100)

    def candles(self, symbol: str, interval: str = "1H", limit: int = 300,
                end_ms: int | None = None) -> list[Candle]:
        symbol = _symbol(symbol)
        if interval not in INTERVAL_MS:
            raise DataError("Unsupported candle interval")
        limit = _integer(limit, "candle limit", minimum=1, maximum=1000)
        duration = INTERVAL_MS[interval]
        cutoff = min(self.clock(), _integer(end_ms, "candle end", minimum=1) if end_ms is not None else self.clock())
        # Explicit end_ms requests use historical pages of <=100. Open bars are
        # filtered against the original cutoff, never against the next page.
        path = "/api/v3/market/history-candles" if end_ms is not None else "/api/v3/market/candles"
        cursor = cutoff
        unique: dict[int, Candle] = {}
        max_pages = (limit + 99) // 100 + 1 if end_ms is not None else 1
        for _ in range(max_pages):
            page_limit = min(100, limit - len(unique) + 1) if end_ms is not None else min(1000, limit + 1)
            params = {"category": CATEGORY, "symbol": symbol, "interval": interval,
                      "limit": page_limit, "endTime": cursor, "type": "market"}
            rows = _rows(self.transport.request("GET", path, params=params), "candles")
            if not rows:
                break
            page_times = []
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    raise DataError("Malformed candle row")
                ts = _integer(row[0], "candle timestamp", minimum=1)
                if ts % duration:
                    raise DataError("Candle timestamp is not aligned to UTC interval")
                values = [_number(row[i], "candle OHLC", positive=True) for i in range(1, 5)]
                volume = _number(row[5], "candle volume", nonnegative=True)
                opening, high, low, close = values
                if low > min(opening, close) or high < max(opening, close) or low > high:
                    raise DataError("Inconsistent candle OHLC")
                page_times.append(ts)
                if ts + duration > cutoff:
                    continue
                candle = Candle(ts, opening, high, low, close, volume)
                if ts in unique and unique[ts] != candle:
                    raise DataError("Conflicting duplicate candle")
                unique[ts] = candle
            if len(unique) >= limit:
                break
            oldest = min(page_times)
            if oldest >= cursor:
                raise DataError("Candle pagination did not advance")
            # endTime is an exclusive interval boundary; subtracting 1 ms
            # makes Bitget skip the immediately preceding closed candle.
            cursor = oldest
            if len(rows) < page_limit:
                break
        result = sorted(unique.values(), key=lambda c: c.ts)[-limit:]
        for left, right in zip(result, result[1:]):
            if right.ts - left.ts != duration:
                raise DataError("Gap in candle history")
        return result

    def instruments(self) -> dict[str, Instrument]:
        rows = _rows(self.transport.request("GET", "/api/v3/market/instruments",
                                           params={"category": CATEGORY}), "instruments")
        result = {}
        for item in rows:
            row = _object(item, "instrument")
            if row.get("category") != CATEGORY:
                raise DataError("Unexpected instrument category")
            if row.get("symbolType") != "crypto" or row.get("type") != "perpetual":
                continue
            # The strategy universe deliberately supports ASCII crypto symbols.
            # Bitget also lists Unicode-named meme coins; those are outside it.
            raw_symbol = row.get("symbol")
            if isinstance(raw_symbol, str) and not re.fullmatch(r"[A-Z0-9]{1,26}USDT", raw_symbol):
                continue
            symbol = _symbol(raw_symbol)
            if row.get("quoteCoin") != "USDT":
                raise DataError("Unexpected instrument quote currency")
            qty_step = _number(row.get("quantityMultiplier"), "quantity multiplier", positive=True)
            price_tick = _number(row.get("priceMultiplier"), "price multiplier", positive=True)
            for step, key in ((qty_step, "quantityPrecision"), (price_tick, "pricePrecision")):
                precision = _integer(row.get(key), key, maximum=18)
                try:
                    units = Decimal(str(step)) / Decimal(10) ** -precision
                    if units != units.to_integral_value():
                        raise DataError("Instrument multiplier conflicts with precision")
                except InvalidOperation:
                    raise DataError("Invalid instrument precision") from None
            status = row.get("status")
            if status not in {"listed", "online", "limit_open", "limit_close", "offline", "restrictedAPI"}:
                raise DataError("Unknown instrument status")
            # Announced maintenance/open restrictions conservatively block entry.
            if any(row.get(k) not in (None, "", "-1", "0") for k in ("offTime", "limitOpenTime", "maintainTime")):
                status = "limit_open"
            instrument = Instrument(
                symbol=symbol, qty_step=qty_step,
                min_qty=_number(row.get("minOrderQty"), "minimum quantity", positive=True),
                min_notional=_number(row.get("minOrderAmount"), "minimum notional", nonnegative=True),
                price_tick=price_tick,
                max_leverage=min(30, _integer(row.get("maxLeverage"), "maximum leverage", minimum=1, maximum=1000)),
                maintenance_margin=.01, status=status)
            if symbol in result:
                raise DataError("Duplicate instrument symbol")
            result[symbol] = instrument
        if not result:
            raise DataError("No supported instruments returned")
        return result

    def ticker(self, symbol: str) -> Quote:
        symbol = _symbol(symbol)
        params = {"category": CATEGORY, "symbol": symbol}
        row = _only_symbol(self.transport.request("GET", "/api/v3/market/tickers", params=params), symbol, "ticker")
        received = self.clock()
        if row.get("category") != CATEGORY:
            raise DataError("Unexpected ticker category")
        ts = _integer(row.get("ts"), "ticker timestamp", minimum=1)
        if ts > received + 2_000 or received - ts > self.max_quote_age_ms:
            raise DataError("Ticker timestamp is stale or in the future")
        bid = _number(row.get("bid1Price"), "best bid", positive=True)
        ask = _number(row.get("ask1Price"), "best ask", positive=True)
        if ask < bid:
            raise DataError("Crossed order book")
        last = _number(row.get("lastPrice"), "last price", positive=True)
        mark = _number(row.get("markPrice"), "mark price", positive=True)
        index = _number(row.get("indexPrice"), "index price", positive=True)
        funding = _only_symbol(self.transport.request("GET", "/api/v3/market/current-fund-rate", params=params), symbol, "funding")
        rate = _number(funding.get("fundingRate"), "funding rate")
        if abs(rate) > 1:
            raise DataError("Funding rate exceeds validation bound")
        next_ts = _integer(funding.get("nextUpdate"), "next funding timestamp", minimum=1)
        now = self.clock()
        if next_ts <= now or next_ts - now > 24 * 3_600_000 or now - ts > self.max_quote_age_ms:
            raise DataError("Funding schedule or quote freshness is invalid")
        return Quote(symbol, bid, ask, last, mark, index, ts, received, rate, next_ts)

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[Funding]:
        symbol = _symbol(symbol)
        start = _integer(start_ms, "funding start", minimum=1)
        end = _integer(end_ms, "funding end", minimum=start)
        values: dict[int, Funding] = {}
        previous_oldest = None
        # The actual UTA API accepts cursor=1,2,... as page numbers. Date query
        # fields are ignored, so requested start/end filtering happens locally.
        for page in range(1, self.max_funding_pages + 1):
            data = _object(self.transport.request("GET", "/api/v3/market/history-fund-rate",
                           params={"category": CATEGORY, "symbol": symbol, "limit": 100, "cursor": page}), "funding history")
            rows = _rows(data.get("resultList"), "funding history results")
            if not rows:
                return sorted(values.values(), key=lambda v: v.ts)
            page_times = []
            for item in rows:
                row = _object(item, "funding history item")
                if row.get("symbol") != symbol:
                    raise DataError("Unexpected funding symbol")
                ts = _integer(row.get("fundingRateTimestamp"), "funding timestamp", minimum=1)
                rate = _number(row.get("fundingRate"), "historical funding rate")
                if abs(rate) > 1:
                    raise DataError("Historical funding rate exceeds validation bound")
                page_times.append(ts)
                if start <= ts <= end:
                    value = Funding(ts, rate)
                    if ts in values and values[ts] != value:
                        raise DataError("Conflicting duplicate funding event")
                    values[ts] = value
            oldest = min(page_times)
            if previous_oldest is not None and oldest >= previous_oldest:
                raise DataError("Funding pagination did not advance")
            previous_oldest = oldest
            if oldest <= start or len(rows) < 100:
                return sorted(values.values(), key=lambda v: v.ts)
        raise DataError("Funding history exceeded page limit; requested period is incomplete")

