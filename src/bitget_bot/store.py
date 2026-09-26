"""One writer, atomic portfolio snapshots, append-only decision/audit history."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time

class WriterLock:
    def __init__(self, path):
        self.path = Path(str(path) + ".lock")
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            # Windows denies reads of a byte locked by another handle.
            # Inspect file size instead, then try locking without touching it.
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self.stream.close()
            self.stream = None
            raise RuntimeError("another writer already owns this ledger") from None
        return self

    def __exit__(self, *args):
        if self.stream:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_UN)
            self.stream.close()

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions (symbol TEXT, ts INTEGER, reason TEXT, PRIMARY KEY(symbol,ts));
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts INTEGER, kind TEXT, symbol TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, value REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS candles (symbol TEXT, interval_ms INTEGER, ts INTEGER, payload TEXT, PRIMARY KEY(symbol,interval_ms,ts));
        """)
        self.db.commit()

    def initialize(self, settings):
        current = self.load()
        if current is not None:
            if current.get("fingerprint") != settings.fingerprint or current.get("mode") != settings.mode:
                raise ValueError("ledger/config mismatch; review existing positions before configuration migration")
            return current
        state = dict(schema=1, mode=settings.mode, fingerprint=settings.fingerprint,
                     cash=settings.initial_equity, equity=settings.initial_equity,
                     peak=settings.initial_equity, positions={}, cooldown={},
                     status="STARTING", halted=False, halt_reason="", pause_until=0,
                     started_ms=int(time.time()*1000), last_cycle_ms=0, trades=0,
                     fees=0.0, funding=0.0, realized_pnl=0.0, last_error="")
        with self.transaction():
            self.save(state)
        return state

    def load(self):
        row = self.db.execute("SELECT payload FROM portfolio WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def save(self, state):
        self.db.execute("INSERT OR REPLACE INTO portfolio VALUES(1,?)", (json.dumps(state, allow_nan=False),))

    def event(self, ts, kind, symbol="", **payload):
        self.db.execute("INSERT INTO events(ts,kind,symbol,payload) VALUES(?,?,?,?)", (ts,kind,symbol,json.dumps(payload,allow_nan=False)))

    def decide(self, symbol, ts, reason):
        result = self.db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?)", (symbol,ts,reason))
        return result.rowcount == 1

    def decided(self, symbol, ts):
        return self.db.execute("SELECT 1 FROM decisions WHERE symbol=? AND ts=?", (symbol,ts)).fetchone() is not None

    def baseline(self, now_ms, fallback):
        row = self.db.execute("SELECT value FROM equity WHERE ts<=? ORDER BY ts DESC LIMIT 1", (now_ms-86400000,)).fetchone()
        if row is None:
            row = self.db.execute("SELECT value FROM equity ORDER BY ts LIMIT 1").fetchone()
        return row[0] if row else fallback

    def record_equity(self, ts, equity):
        self.db.execute("INSERT OR REPLACE INTO equity VALUES(?,?)", (ts,equity))

    def cache_candles(self, symbol, interval_ms, candles):
        from dataclasses import asdict
        self.db.executemany("INSERT OR IGNORE INTO candles VALUES(?,?,?,?)", [(symbol,interval_ms,c.ts,json.dumps(asdict(c))) for c in candles])

    def prune(self, now_ms):
        self.db.execute("DELETE FROM equity WHERE ts<?", (now_ms-10*86400000,))
        self.db.execute("DELETE FROM candles WHERE interval_ms=60000 AND ts<?", (now_ms-10*86400000,))

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()


def read_status(path):
    path = Path(path).resolve()
    if not path.exists():
        return {"status":"NOT_STARTED"}
    with sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=3) as db:
        row = db.execute("SELECT payload FROM portfolio WHERE id=1").fetchone()
        if not row:
            return {"status":"NOT_STARTED"}
        state = json.loads(row[0])
        events = db.execute("SELECT ts,kind,symbol,payload FROM events ORDER BY id DESC LIMIT 25").fetchall()
        state["events"] = [{"ts":t,"kind":k,"symbol":s,"detail":json.loads(p)} for t,k,s,p in events]
        return state
