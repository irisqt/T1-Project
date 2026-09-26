"""Download immutable, fixed-window public OHLC research data with resumable pages.

This script never loads credentials, calls account/order APIs, or evaluates a
strategy. The protected holdout is checked only for timestamp completeness.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bitget_bot.exchange import MarketClient  # noqa: E402

HOUR = 3_600_000
DAY = 24 * HOUR
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FIELDS = ("ts", "open", "high", "low", "close", "volume")


def emit(**data):
    print(json.dumps(data, ensure_ascii=False, allow_nan=False), flush=True)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include its UTC offset")
    result = int(parsed.timestamp() * 1000)
    if result % HOUR:
        raise ValueError("timestamp must be aligned to an hour")
    return result


def iso(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def validate_rows(rows, start, end, *, require_full=False):
    previous = None
    for row in rows:
        if set(row) != set(FIELDS):
            raise ValueError("unexpected OHLC fields")
        stamp = row["ts"]
        if (isinstance(stamp, bool) or not isinstance(stamp, int)
                or stamp % HOUR or not start <= stamp < end):
            raise ValueError("invalid OHLC timestamp")
        if previous is not None and stamp - previous != HOUR:
            raise ValueError("duplicate or missing hourly candle")
        previous = stamp
        values = [row[field] for field in FIELDS[1:]]
        if any(isinstance(value, bool) or not isinstance(value, (float, int))
               or not math.isfinite(value) for value in values):
            raise ValueError("nonfinite candle value")
        opening, high, low, close, volume = values
        if (min(opening, high, low, close) <= 0 or volume < 0
                or low > min(opening, close) or high < max(opening, close)):
            raise ValueError("invalid candle OHLC")
    if rows and rows[-1]["ts"] != end - HOUR:
        raise ValueError("history does not reach the fixed end boundary")
    if require_full and (len(rows) != (end - start) // HOUR
                         or rows[0]["ts"] != start):
        raise ValueError("requested history is incomplete")


def fetch_symbol(symbol, start, end, checkpoint_dir):
    path = checkpoint_dir / (symbol + ".json")
    metadata = {"schema": 1, "symbol": symbol, "start_ms": start, "end_ms": end}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if any(saved.get(key) != value for key, value in metadata.items()):
            raise ValueError("checkpoint does not match requested data window")
        rows = saved["rows"]
        validate_rows(rows, start, end)
        unique = {row["ts"]: row for row in rows}
    else:
        unique = {}
    cursor = min(unique) if unique else end
    client = MarketClient()
    pages = 0
    emit(event="DOWNLOAD_START", symbol=symbol, resumed_bars=len(unique))
    while cursor > start:
        page = client.candles(symbol, "1H", 100, end_ms=cursor)
        if not page:
            raise ValueError(symbol + ": public history exhausted before requested start")
        earliest = page[0].ts
        if earliest >= cursor:
            raise ValueError("history pagination did not advance")
        for candle in page:
            if start <= candle.ts < end:
                row = asdict(candle)
                if candle.ts in unique and unique[candle.ts] != row:
                    raise ValueError("conflicting duplicate public candle")
                unique[candle.ts] = row
        cursor = earliest
        pages += 1
        if pages % 5 == 0 or cursor <= start:
            rows = [unique[stamp] for stamp in sorted(unique)]
            validate_rows(rows, start, end)
            atomic_json(path, {**metadata, "rows": rows})
        if pages % 20 == 0 or cursor <= start:
            emit(event="DOWNLOAD_PROGRESS", symbol=symbol, bars=len(unique),
                 earliest_utc=iso(max(start, earliest)))
        time.sleep(0.2)
    rows = [unique[stamp] for stamp in sorted(unique)]
    validate_rows(rows, start, end, require_full=True)
    emit(event="DOWNLOAD_COMPLETE", symbol=symbol, bars=len(rows))
    return rows


def validate_dataset(dataset, reference, start, end, holdout_start):
    report = {}
    expected = list(range(start, end, HOUR))
    for symbol in SYMBOLS:
        rows = dataset["symbols"][symbol]
        validate_rows(rows, start, end, require_full=True)
        if [row["ts"] for row in rows] != expected:
            raise ValueError("timestamps are not identical across symbols")
        by_ts = {row["ts"]: row for row in rows if row["ts"] < holdout_start}
        original = [row for row in reference["symbols"][symbol]
                    if start <= row["ts"] < holdout_start]
        mismatches = sum(by_ts.get(row["ts"]) != row for row in original)
        report[symbol] = {
            "bars": len(rows), "first_open_utc": iso(rows[0]["ts"]),
            "last_open_utc": iso(rows[-1]["ts"]), "missing_hour_count": 0,
            "duplicate_timestamp_count": 0, "pre_holdout_overlap_bars": len(original),
            "pre_holdout_overlap_mismatches": mismatches,
            "heldout_bars_timestamp_check_only": sum(row["ts"] >= holdout_start for row in rows),
            "canonical_rows_sha256": hashlib.sha256(json.dumps(
                rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        }
        if not original or mismatches:
            raise ValueError(symbol + ": pre-holdout overlap validation failed")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=720)
    parser.add_argument("--end", default="2026-09-23T04:00:00Z")
    parser.add_argument("--holdout-start", default="2026-08-19T01:00:00Z")
    parser.add_argument("--reference", type=Path, default=ROOT / "artifacts/history_180d_20260923.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/history_720d_20260923.json")
    args = parser.parse_args()
    if not 3 <= args.days <= 1095:
        raise ValueError("days must be 3..1095")
    end = timestamp(args.end)
    start = end - args.days * DAY
    holdout_start = timestamp(args.holdout_start)
    if not start < holdout_start < end:
        raise ValueError("holdout start must be within the fixed data window")
    if end > int(time.time() * 1000):
        raise ValueError("end must not be in the future")
    original_hash = digest(args.reference)
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    coverage_path = args.output.with_suffix(".coverage.json")
    if args.output.exists():
        dataset = json.loads(args.output.read_text(encoding="utf-8"))
        if dataset.get("requested_start_ms") != start or dataset.get("end_exclusive_ms") != end:
            raise ValueError("existing immutable output uses a different data window")
    else:
        dataset = {
            "schema": 1, "source": "Bitget UTA v3 public market/history-candles",
            "downloaded_ms": int(time.time() * 1000), "requested_start_ms": start,
            "end_exclusive_ms": end, "holdout_start_ms": holdout_start,
            "symbols": {}, "limitations": [
                "Current fixed universe; not a survivorship-free universe",
                "Trade-price OHLC; no historical liquidation tiers or order book",
                "OHLC only; historical funding requires independent collection or explicit cost scenarios",
                "Protected holdout is not evaluated by this data-integrity script",
            ],
        }
        checkpoint_dir = args.output.parent / (args.output.stem + "_checkpoints")
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(fetch_symbol, symbol, start, end, checkpoint_dir): symbol
                    for symbol in SYMBOLS}
            for job in as_completed(jobs):
                dataset["symbols"][jobs[job]] = job.result()
        dataset["symbols"] = {symbol: dataset["symbols"][symbol] for symbol in SYMBOLS}
        validate_dataset(dataset, reference, start, end, holdout_start)
        if args.output.exists():
            raise ValueError("output appeared during download; refusing overwrite")
        atomic_json(args.output, dataset)
    symbols = validate_dataset(dataset, reference, start, end, holdout_start)
    if digest(args.reference) != original_hash:
        raise ValueError("reference dataset changed during download")
    report = {
        "schema": 1, "validated_utc": iso(int(time.time() * 1000)),
        "output": str(args.output), "dataset_sha256": digest(args.output),
        "reference": str(args.reference), "reference_sha256": original_hash,
        "fixed_start_utc": iso(start), "fixed_end_exclusive_utc": iso(end),
        "protected_holdout_start_utc": iso(holdout_start),
        "all_symbol_timestamps_identical": True, "reference_file_unchanged": True,
        "no_strategy_or_return_evaluation": True, "symbols": symbols,
    }
    atomic_json(coverage_path, report)
    emit(event="DATASET_VALIDATED", dataset_sha256=report["dataset_sha256"],
         coverage_file=str(coverage_path), bars_per_symbol=(end - start) // HOUR,
         first_open_utc=iso(start), end_exclusive_utc=iso(end))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit(event="DOWNLOAD_FAILED", error_type=type(exc).__name__, message=str(exc))
        raise SystemExit(1) from None
