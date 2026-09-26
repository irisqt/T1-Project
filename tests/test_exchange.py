"""Failure-oriented tests; fixtures never load real credentials or send requests."""
import base64
import hashlib
import hmac
import json
import unittest
import urllib.parse
from dataclasses import asdict
from unittest.mock import Mock

from bitget_bot.exchange import (
    BASE_URL, MAX_RESPONSE_BYTES, Credentials, DataError, DemoTransport,
    ExchangeError, MarketClient, PrivateReadOnlyClient, SafetyError, Transport,
    _RejectRedirects,
)

HOUR = 3_600_000
NOW = 1_788_480_000_000
CREDENTIALS = Credentials("fixture-key", "fixture-secret", "fixture-passphrase")


def envelope(data):
    return 200, json.dumps({"code": "00000", "data": data}).encode()


class QueueSender:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def market(*payloads, **kwargs):
    sender = QueueSender(*(envelope(value) for value in payloads))
    transport = Transport(sender=sender, clock=lambda: NOW, sleeper=lambda _: None)
    return MarketClient(transport, clock=lambda: NOW, **kwargs), sender


def candle(ts, close="101"):
    return [str(ts), "100", "110", "90", close, "12", "1200"]


def instrument(**changes):
    result = {"symbol": "BTCUSDT", "category": "USDT-FUTURES", "symbolType": "crypto",
              "type": "perpetual", "quoteCoin": "USDT", "quantityMultiplier": "0.0001",
              "priceMultiplier": "0.1", "quantityPrecision": "4", "pricePrecision": "1",
              "minOrderQty": "0.0001", "minOrderAmount": "5", "maxLeverage": "150",
              "status": "online", "offTime": "-1", "limitOpenTime": "-1", "maintainTime": ""}
    result.update(changes)
    return result


def ticker(**changes):
    result = {"symbol": "BTCUSDT", "category": "USDT-FUTURES", "ts": str(NOW - 100),
              "bid1Price": "100", "ask1Price": "100.1", "lastPrice": "100.05",
              "markPrice": "100.07", "indexPrice": "100.08"}
    result.update(changes)
    return result


def funding_current(**changes):
    result = {"symbol": "BTCUSDT", "fundingRate": "0.0001", "nextUpdate": str(NOW + HOUR)}
    result.update(changes)
    return result


def funding(ts, rate="0.0001"):
    return {"symbol": "BTCUSDT", "fundingRateTimestamp": str(ts), "fundingRate": rate}


class TransportTests(unittest.TestCase):
    def test_production_cannot_write_even_with_realistic_credentials(self):
        sender = QueueSender()
        transport = Transport(CREDENTIALS, sender=sender)
        for method in ("POST", "DELETE", "PUT", "PATCH"):
            with self.subTest(method=method), self.assertRaises(SafetyError):
                transport.request(method, "/api/v3/trade/place-order", private=True,
                                  payload={"clientOid": "saved-1"})
        self.assertEqual(sender.calls, [])

    def test_no_credential_exfiltration_by_origin_or_path(self):
        for origin in ("http://api.bitget.com", "https://api.bitget.com.evil.invalid",
                       "https://user@api.bitget.com", "https://api.bitget.com:443"):
            with self.subTest(origin=origin), self.assertRaises(SafetyError):
                Transport(CREDENTIALS, base_url=origin)
        sender = QueueSender()
        transport = Transport(CREDENTIALS, sender=sender)
        for path in ("https://evil.invalid/", "//evil.invalid/", "/api/v3/account/withdrawal",
                     "/api/v3/account/info?forward=evil", "/api/v3/account/../withdrawal"):
            with self.subTest(path=path), self.assertRaises(SafetyError):
                transport.request("GET", path, private=True)
        self.assertEqual(sender.calls, [])

    def test_redirect_is_never_followed_and_never_retried(self):
        sender = QueueSender((302, b""))
        with self.assertRaises(SafetyError):
            Transport(CREDENTIALS, sender=sender).request("GET", "/api/v3/account/info", private=True)
        self.assertEqual(len(sender.calls), 1)
        with self.assertRaises(SafetyError):
            _RejectRedirects().redirect_request(None, None, 307, "", {}, "https://evil.invalid")

    def test_signs_the_exact_transmitted_query_and_body(self):
        sender = QueueSender(envelope({"orderId": "test"}))
        transport = DemoTransport(CREDENTIALS, demo_keys_confirmed=True, allow_writes=True,
                                  sender=sender, clock=lambda: NOW)
        transport.request("POST", "/api/v3/trade/place-order", private=True,
                          payload={"clientOid": "saved-1", "category": "USDT-FUTURES", "qty": "0.001"})
        request, timeout = sender.calls[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        target = urllib.parse.urlsplit(request.full_url).path
        message = str(NOW).encode() + b"POST" + target.encode() + request.data
        expected = base64.b64encode(hmac.new(b"fixture-secret", message, hashlib.sha256).digest()).decode()
        self.assertEqual(headers["access-sign"], expected)
        self.assertNotIn(b": ", request.data)
        self.assertEqual(headers["paptrading"], "1")
        self.assertEqual(timeout, 10)

    def test_get_query_is_sorted_encoded_and_signed_exactly(self):
        sender = QueueSender(envelope({}))
        transport = Transport(CREDENTIALS, sender=sender, clock=lambda: NOW)
        transport.request("GET", "/api/v3/account/info", private=True,
                          params={"z": "space + percent%", "a": 2})
        request = sender.calls[0][0]
        self.assertTrue(request.full_url.endswith("?a=2&z=space%20%2B%20percent%25"))
        target = request.full_url.removeprefix(BASE_URL)
        expected = base64.b64encode(hmac.new(b"fixture-secret", (str(NOW) + "GET" + target).encode(), hashlib.sha256).digest()).decode()
        self.assertEqual(request.get_header("Access-sign"), expected)
        self.assertIsNone(request.data)

    def test_public_requests_never_send_credentials(self):
        sender = QueueSender(envelope([]))
        Transport(CREDENTIALS, sender=sender).request("GET", "/api/v3/market/instruments")
        self.assertFalse(any(k.lower().startswith("access-") for k, _ in sender.calls[0][0].header_items()))

    def test_get_retries_transient_failures_only_and_is_bounded(self):
        sender = QueueSender((503, b"private error detail"), (429, b""), envelope([]))
        sleeps = []
        result = Transport(sender=sender, sleeper=sleeps.append).request("GET", "/api/v3/market/instruments")
        self.assertEqual(result, [])
        self.assertEqual(len(sender.calls), 3)
        self.assertEqual(sleeps, [.5, 1.0])
        sender = QueueSender((401, b"do not leak me"))
        with self.assertRaises(ExchangeError) as caught:
            Transport(sender=sender).request("GET", "/api/v3/market/instruments")
        self.assertNotIn("do not leak", str(caught.exception))
        self.assertEqual(len(sender.calls), 1)

    def test_uncertain_post_never_retries(self):
        for failure in ((503, b""), ExchangeError("Network failure", retryable=True)):
            with self.subTest(failure=type(failure).__name__):
                sender = QueueSender(failure)
                transport = DemoTransport(CREDENTIALS, demo_keys_confirmed=True, allow_writes=True, sender=sender)
                with self.assertRaises(ExchangeError):
                    transport.request("POST", "/api/v3/trade/place-order", private=True,
                                      payload={"clientOid": "saved-id"})
                self.assertEqual(len(sender.calls), 1)

    def test_demo_requires_separate_key_confirmation_and_opt_in(self):
        with self.assertRaises(SafetyError):
            DemoTransport(CREDENTIALS)
        sender = QueueSender()
        transport = DemoTransport(CREDENTIALS, demo_keys_confirmed=True, sender=sender)
        with self.assertRaises(SafetyError):
            transport.request("POST", "/api/v3/trade/place-order", private=True,
                              payload={"clientOid": "persisted-id"})
        transport = DemoTransport(CREDENTIALS, demo_keys_confirmed=True, allow_writes=True, sender=sender)
        for path, payload in (("/api/v3/trade/place-order", {}),
                              ("/api/v3/account/transfer", {"clientOid": "id"}),
                              ("/api/v3/account/withdrawal", {"clientOid": "id"})):
            with self.subTest(path=path), self.assertRaises(SafetyError):
                transport.request("POST", path, private=True, payload=payload)
        self.assertEqual(sender.calls, [])

    def test_malformed_oversized_and_missing_data_fail_closed(self):
        for response in ((200, b"not json"), (200, b"[]"),
                         (200, b'{"code":"00000","data":null}'),
                         (200, b"x" * (MAX_RESPONSE_BYTES + 1))):
            with self.subTest(length=len(response[1])), self.assertRaises(DataError):
                Transport(sender=QueueSender(response)).request("GET", "/api/v3/market/instruments")

    def test_error_messages_and_credential_repr_redact_secret_values(self):
        self.assertEqual(repr(CREDENTIALS), "Credentials()")
        sender = QueueSender((200, b'{"code":"40009","msg":"fixture-secret","data":null}'))
        with self.assertRaises(ExchangeError) as caught:
            Transport(sender=sender).request("GET", "/api/v3/market/instruments")
        self.assertNotIn("fixture-secret", str(caught.exception))
        self.assertEqual(caught.exception.code, "40009")
        for timeout in (0, -1, 31, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(SafetyError):
                Transport(timeout=timeout)
        with self.assertRaises(SafetyError):
            Credentials("header\r\ninjection", "x", "y")

    def test_diagnostics_do_not_return_identity_balance_or_ips(self):
        sender = QueueSender(envelope({"userId": "sensitive-uid", "ips": "192.0.2.1",
                                       "permissions": ["uta_mgt", "uta_trade"]}),
                             envelope({"accountMode": "unified", "holdMode": "one_way_mode"}))
        client = PrivateReadOnlyClient(transport=Transport(CREDENTIALS, sender=sender))
        status = client.check_credentials()
        self.assertTrue(status.authenticated and status.unified_account and status.withdrawal_disabled)
        self.assertTrue(status.ip_restricted)
        self.assertNotIn("sensitive-uid", str(asdict(status)))
        self.assertNotIn("192.0.2.1", str(asdict(status)))
        self.assertTrue(all(call[0].get_method() == "GET" for call in sender.calls))

    def test_diagnostics_fail_closed_for_withdraw_permission_and_unreadable_settings(self):
        sender = QueueSender(envelope({"ips": "", "permissions": ["withdraw"]}),
                             (200, b'{"code":"40014","msg":"private account detail","data":null}'))
        status = PrivateReadOnlyClient(transport=Transport(CREDENTIALS, sender=sender)).check_credentials()
        self.assertTrue(status.authenticated)
        self.assertFalse(status.withdrawal_disabled or status.settings_readable or status.unified_account)
        self.assertEqual(status.error_code, "40014")


class MarketTests(unittest.TestCase):
    def test_candles_sort_deduplicate_and_exclude_open_bar(self):
        client, _ = market([candle(NOW), candle(NOW - HOUR), candle(NOW - 2 * HOUR), candle(NOW - HOUR)])
        result = client.candles("BTCUSDT", limit=3)
        self.assertEqual([c.ts for c in result], [NOW - 2 * HOUR, NOW - HOUR])

    def test_candle_timestamp_and_prices_must_be_consistent(self):
        cases = [[candle(NOW - HOUR, "NaN")], [candle(NOW - HOUR, "200")],
                 [candle(NOW - HOUR + 1)], [candle(NOW - HOUR), candle(NOW - HOUR, "102")],
                 [candle(NOW - HOUR), candle(NOW - 3 * HOUR)]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(DataError):
                market(rows)[0].candles("BTCUSDT")

    def test_history_pages_advance_backward_without_accepting_open_candle(self):
        first = [candle(NOW - i * HOUR) for i in range(100)]
        second = [candle(NOW - i * HOUR) for i in range(100, 200)]
        third = [candle(NOW - i * HOUR) for i in range(200, 300)]
        fourth = [candle(NOW - 300 * HOUR)]
        client, sender = market(first, second, third, fourth)
        result = client.candles("BTCUSDT", limit=300, end_ms=NOW)
        self.assertEqual(len(result), 300)
        self.assertEqual(result[-1].ts, NOW - HOUR)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(sender.calls[1][0].full_url).query)
        self.assertEqual(int(query["endTime"][0]), NOW - 99 * HOUR)
        for request, _ in sender.calls:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
            self.assertLessEqual(int(query["limit"][0]), 100)

    def test_history_chained_at_oldest_open_has_no_boundary_gap(self):
        client, _ = market([candle(NOW - i * HOUR) for i in range(1, 4)],
                           [candle(NOW - i * HOUR) for i in range(4, 7)])
        recent = client.candles("BTCUSDT", limit=3, end_ms=NOW)
        older = client.candles("BTCUSDT", limit=3, end_ms=recent[0].ts)
        merged = older + recent
        self.assertEqual([right.ts-left.ts for left, right in zip(merged, merged[1:])], [HOUR]*5)

    def test_funding_page_limit_obeys_documented_cap(self):
        with self.assertRaises(DataError):
            MarketClient(max_funding_pages=101)

    def test_instrument_multiplier_is_not_decimal_place_count(self):
        client, _ = market([instrument(priceMultiplier="0.5", pricePrecision="1")])
        row = client.instruments()["BTCUSDT"]
        self.assertEqual(row.price_tick, .5)
        self.assertEqual(row.qty_step, .0001)
        self.assertEqual(row.min_notional, 5)
        self.assertEqual(row.max_leverage, 30)
        self.assertEqual(row.maintenance_margin, .01)

    def test_instruments_reject_bad_metadata_and_disable_maintenance(self):
        for changes in ({"quantityMultiplier": "0"}, {"maxLeverage": "NaN"},
                        {"priceMultiplier": "0.005"}, {"status": "unrecognized"}):
            with self.subTest(changes=changes), self.assertRaises(DataError):
                market([instrument(**changes)])[0].instruments()
        row = market([instrument(maintainTime=str(NOW + HOUR))])[0].instruments()["BTCUSDT"]
        self.assertEqual(row.status, "limit_open")

    def test_unsupported_unicode_instruments_do_not_disable_supported_universe(self):
        client, _ = market([instrument(), instrument(symbol="龙虾USDT")])
        self.assertEqual(list(client.instruments()), ["BTCUSDT"])
    def test_ticker_contains_exchange_time_and_actual_funding_schedule(self):
        client, _ = market([ticker()], [funding_current()])
        result = client.ticker("BTCUSDT")
        self.assertEqual(result.ts, NOW - 100)
        self.assertEqual(result.received_ts, NOW)
        self.assertEqual(result.next_funding_ts, NOW + HOUR)
        self.assertEqual(result.funding_rate, .0001)

    def test_stale_future_crossed_and_malformed_quotes_are_rejected(self):
        for changes in ({"ts": str(NOW - 60_000)}, {"ts": str(NOW + 60_000)},
                        {"bid1Price": "101"}, {"markPrice": "inf"}, {"indexPrice": "0"},
                        {"symbol": "ETHUSDT"}, {"category": "SPOT"}):
            with self.subTest(changes=changes), self.assertRaises(DataError):
                market([ticker(**changes)])[0].ticker("BTCUSDT")
        with self.assertRaises(DataError):
            market([ticker()], [funding_current(nextUpdate=str(NOW))])[0].ticker("BTCUSDT")

    def test_funding_uses_numeric_page_cursor_and_local_date_filter(self):
        first = [funding(NOW - i * HOUR) for i in range(100)]
        second = [funding(NOW - i * HOUR) for i in range(100, 120)]
        client, sender = market({"resultList": first}, {"resultList": second})
        result = client.funding_history("BTCUSDT", NOW - 110 * HOUR, NOW - 90 * HOUR)
        self.assertEqual(len(result), 21)
        self.assertEqual(result[0].ts, NOW - 110 * HOUR)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(sender.calls[1][0].full_url).query)
        self.assertEqual(query["cursor"], ["2"])
        self.assertNotIn("startTime", query)

    def test_funding_pagination_never_silently_loops_or_truncates(self):
        rows = [funding(NOW - i * HOUR) for i in range(100)]
        with self.assertRaisesRegex(DataError, "did not advance"):
            market({"resultList": rows}, {"resultList": rows})[0].funding_history("BTCUSDT", NOW - 1000 * HOUR, NOW)
        with self.assertRaisesRegex(DataError, "incomplete"):
            market({"resultList": rows}, max_funding_pages=1)[0].funding_history("BTCUSDT", NOW - 1000 * HOUR, NOW)

    def test_invalid_requests_do_not_reach_transport(self):
        client, sender = market()
        for request in (lambda: client.candles("BTCUSDT&evil=1"),
                        lambda: client.candles("BTCUSDT", interval="2H"),
                        lambda: client.candles("BTCUSDT", limit=0),
                        lambda: client.funding_history("BTCUSDT", NOW, NOW - 1)):
            with self.assertRaises(DataError):
                request()
        self.assertEqual(sender.calls, [])


if __name__ == "__main__":
    unittest.main()

