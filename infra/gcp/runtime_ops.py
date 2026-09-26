"""Root-owned systemd helper: restart hung workers and take SQLite online backups."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from contextlib import closing
import gzip
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

SERVICE = "bitget-bot.service"
DEFAULT_STATE = Path("/var/lib/bitget/data")
BACKUP_PATTERN = re.compile(r"^trader-\d{8}T\d{6}Z-[0-9a-f]{8}\.sqlite3$")

def heartbeat_is_stale(path: Path, maximum_age: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    try:
        modified = path.stat().st_mtime
        payload = json.loads(path.read_text(encoding="utf-8"))
        stamp = float(payload["timestamp"])
        # Reject future clock skew as well as stale or malformed heartbeats.
        return not math.isfinite(stamp) or min(modified, stamp) < now - maximum_age or stamp > now + 60
    except (OSError, ValueError, KeyError, TypeError):
        return True

def health(state: Path, maximum_age: int) -> int:
    if subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], check=False).returncode:
        # Never undo an operator's deliberate stop; systemd handles process crashes.
        return 0
    since = subprocess.check_output(
        ["systemctl", "show", SERVICE, "--property=ActiveEnterTimestampMonotonic", "--value"], text=True
    ).strip()
    uptime = float(Path("/proc/uptime").read_text().split()[0])
    if uptime - int(since or "0") / 1_000_000 < maximum_age:
        return 0
    if heartbeat_is_stale(state / "heartbeat.json", maximum_age):
        print("Heartbeat stale or invalid; restarting bitget-bot.service", flush=True)
        subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=60)
    return 0

def readiness(state: Path, maximum_age: int, *, now: float | None = None, started_at: float | None = None) -> dict:
    """Require a current successful paper cycle in both heartbeat and durable ledger."""
    now = time.time() if now is None else now
    heartbeat = state / "heartbeat.json"
    if heartbeat_is_stale(heartbeat, maximum_age, now):
        raise RuntimeError("Worker heartbeat is stale or invalid")
    try:
        payload = json.loads(heartbeat.read_text(encoding="utf-8"))
        stamp = float(payload["timestamp"])
        if not math.isfinite(stamp) or not now - maximum_age <= stamp <= now + 60:
            raise RuntimeError("Worker heartbeat is stale or invalid")
        if started_at is not None and stamp < started_at:
            raise RuntimeError("Worker has not completed a cycle since this service start")
        if payload.get("mode") != "paper" or payload.get("state") != "RUNNING":
            raise RuntimeError("Worker heartbeat does not report a running paper cycle")
        database = state / "trader.sqlite3"
        if not database.is_file():
            raise RuntimeError("Worker ledger does not exist")
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as connection:
            row = connection.execute("SELECT payload FROM portfolio WHERE id=1").fetchone()
        ledger = json.loads(row[0]) if row else {}
        if ledger.get("mode") != "paper" or ledger.get("status") != "RUNNING" or ledger.get("halted") is not False or ledger.get("last_error") != "":
            raise RuntimeError("Worker ledger does not report a running paper cycle")
        cycle_ms = float(ledger["last_cycle_ms"])
        if not math.isfinite(cycle_ms) or abs(cycle_ms - stamp * 1000) > 1:
            raise RuntimeError("Worker heartbeat and ledger cycles differ")
        heartbeat_equity, ledger_equity = float(payload["equity"]), float(ledger["equity"])
        if not all(math.isfinite(value) and value > 0 for value in (heartbeat_equity, ledger_equity)) or not math.isclose(heartbeat_equity, ledger_equity, rel_tol=1e-12, abs_tol=1e-8):
            raise RuntimeError("Worker heartbeat and ledger equity differ or are invalid")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
        raise RuntimeError("Worker heartbeat or ledger cannot be verified") from exc
    return {"timestamp": stamp, "state": "RUNNING", "mode": "paper", "equity": ledger_equity}


def verify(state: Path, maximum_age: int) -> dict:
    if subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], check=False).returncode:
        raise RuntimeError("Worker service is inactive")
    # A retained heartbeat from before a restart must not validate a new process.
    entered = int(subprocess.check_output(
        ["systemctl", "show", SERVICE, "--property=ActiveEnterTimestampMonotonic", "--value"], text=True
    ).strip() or "0") / 1_000_000
    now, monotonic = time.time(), time.monotonic()
    if entered <= 0 or entered > monotonic:
        raise RuntimeError("Worker service start time cannot be verified")
    return readiness(state, maximum_age, now=now, started_at=now - (monotonic - entered))


def backup(database: Path, destination: Path, retain: int = 168) -> Path | None:
    if not database.is_file():
        print("No database exists yet; backup deferred", flush=True)
        return None
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    unique = uuid.uuid4().hex[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = destination / f"trader-{stamp}-{unique}.sqlite3"
    fd, temporary = tempfile.mkstemp(prefix=".pending-", suffix=".sqlite3", dir=destination)
    os.close(fd)
    temporary_path = Path(temporary)
    started = time.monotonic()
    def progress(status: int, remaining: int, total: int) -> None:
        if time.monotonic() - started > 90:
            raise TimeoutError("Online backup exceeded 90 seconds")
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(temporary_path)) as target:
                source.backup(target, pages=256, progress=progress, sleep=0.05)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite backup integrity check failed")
        with temporary_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_path, final)
        backups = sorted((p for p in destination.iterdir() if BACKUP_PATTERN.fullmatch(p.name)), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for obsolete in backups[max(1, retain):]:
            obsolete.unlink()
        return final
    finally:
        temporary_path.unlink(missing_ok=True)

def upload_to_gcs(path: Path, bucket: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", bucket):
        raise ValueError("Invalid GCS bucket name")
    metadata = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(metadata, timeout=10) as response:
        token = json.load(response)["access_token"]
    # Object Creator IAM is sufficient; timestamps prevent overwrite of older backups.
    object_name = f"bitget-paper/{path.name}.gz"
    with tempfile.TemporaryFile() as compressed:
        with path.open("rb") as source, gzip.GzipFile(fileobj=compressed, mode="wb") as output:
            shutil.copyfileobj(source, output)
        length = compressed.tell()
        compressed.seek(0)
        route = "/upload/storage/v1/b/" + urllib.parse.quote(bucket, safe="") + "/o?"
        route += urllib.parse.urlencode({"uploadType": "media", "name": object_name, "ifGenerationMatch": 0})
        connection = http.client.HTTPSConnection("storage.googleapis.com", timeout=90)
        try:
            connection.putrequest("POST", route)
            connection.putheader("Authorization", f"Bearer {token}")
            connection.putheader("Content-Type", "application/gzip")
            connection.putheader("Content-Length", str(length))
            connection.endheaders()
            while chunk := compressed.read(1024 * 1024):
                connection.send(chunk)
            response = connection.getresponse()
            response.read()
            if response.status not in {200, 201}:
                raise RuntimeError(f"GCS backup upload failed: HTTP {response.status}")
        finally:
            connection.close()
    print(f"Off-disk backup saved: gs://{bucket}/{object_name}", flush=True)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["health", "backup", "verify"])
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--max-age", type=int, default=180)
    parser.add_argument("--destination", type=Path, default=Path("/var/lib/bitget/backups"))
    args = parser.parse_args()
    if args.command == "verify":
        try:
            print(json.dumps(verify(args.state, args.max_age), allow_nan=False))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            raise SystemExit(str(exc)) from None
        return
    if args.command == "health":
        raise SystemExit(health(args.state, args.max_age))
    result = backup(args.state / "trader.sqlite3", args.destination)
    if result:
        print(f"Online backup saved: {result.name}", flush=True)
        bucket = os.environ.get("BITGET_BACKUP_BUCKET", "")
        if bucket:
            upload_to_gcs(result, bucket)

if __name__ == "__main__":
    main()
