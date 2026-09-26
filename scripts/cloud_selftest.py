"""Offline deployment checks. Creates only temporary fixture files under artifacts/cloud."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

bundle = load("cloud_bundle", ROOT / "scripts/cloud_bundle.py")
ops = load("runtime_ops", ROOT / "infra/gcp/runtime_ops.py")

class CloudTests(unittest.TestCase):
    def setUp(self):
        target = ROOT / "artifacts/cloud"
        target.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="selftest-", dir=target)
        self.root = Path(self.temporary.name).resolve()
        assert self.root.is_relative_to(target.resolve())
        for directory in ("src/bitget_bot", "infra/gcp", "config", "data", "reference"):
            (self.root / directory).mkdir(parents=True)
        (self.root / "src/bitget_bot/__main__.py").write_text("print('paper')\n")
        (self.root / "infra/gcp/install.sh").write_text("#!/bin/bash\ntrue\n")
        (self.root / "config/paper.toml").write_text('mode = "paper"\n')
        self.archive = self.root / "artifacts/cloud/fixture.tar.gz"

    def tearDown(self):
        # TemporaryDirectory is verified to be contained within this project's artifacts.
        self.temporary.cleanup()

    def test_bundle_excludes_credentials_references_and_state(self):
        for relative in (".env", "data/private.py", "reference/strategy.py", "src/bitget_bot/.env.py"):
            (self.root / relative).write_text("SECRET_SENTINEL_VALUE_12345")
        (self.root / "src/bitget_bot/__pycache__").mkdir()
        (self.root / "src/bitget_bot/__pycache__/private.py").write_text("SECRET_SENTINEL_VALUE_12345")
        bundle.build(self.root, self.archive)
        with tarfile.open(self.archive) as handle:
            for member in handle.getmembers():
                self.assertNotIn(b"SECRET_SENTINEL_VALUE_12345", handle.extractfile(member).read())
            self.assertEqual(set(handle.getnames()), {
                "src/bitget_bot/__main__.py", "infra/gcp/install.sh", "config/paper.toml", "BUILD_MANIFEST.json"
            })

    def test_manifest_checksums_match(self):
        result = bundle.build(self.root, self.archive)
        self.assertEqual(result["sha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        with tarfile.open(self.archive) as handle:
            manifest = json.load(handle.extractfile("BUILD_MANIFEST.json"))
            for row in manifest["files"]:
                self.assertEqual(row["sha256"], hashlib.sha256(handle.extractfile(row["path"]).read()).hexdigest())

    def test_identical_content_has_identical_archive_hash(self):
        first = bundle.build(self.root, self.archive)
        second = bundle.build(self.root, self.archive.with_name("another-name.tar.gz"))
        self.assertEqual(first["sha256"], second["sha256"])

    def test_live_config_refused(self):
        (self.root / "config/paper.toml").write_text('mode = "live"\n')
        with self.assertRaisesRegex(ValueError, "paper mode"):
            bundle.build(self.root, self.archive)

    def test_archive_must_be_in_artifacts(self):
        with self.assertRaisesRegex(ValueError, "artifacts"):
            bundle.build(self.root, self.root / "bad.tar.gz")

    def test_required_files_checked(self):
        (self.root / "src/bitget_bot/__main__.py").unlink()
        with self.assertRaisesRegex(ValueError, "Missing required"):
            bundle.build(self.root, self.archive)

    def test_online_backup_with_open_wal(self):
        database = self.root / "data/trader.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE checks(value TEXT)")
            connection.execute("INSERT INTO checks VALUES ('persisted')")
            connection.commit()
            result = ops.backup(database, self.root / "backups")
            self.assertTrue(result.is_file())
            restored = sqlite3.connect(result)
            try:
                self.assertEqual(restored.execute("SELECT value FROM checks").fetchone()[0], "persisted")
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                restored.close()
        finally:
            connection.close()

    def test_backup_retention_keeps_unrelated_files(self):
        database = self.root / "data/trader.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE checks(value TEXT)")
        connection.commit()
        connection.close()
        backup_dir = self.root / "backups"
        backup_dir.mkdir()
        unrelated = backup_dir / "do-not-delete.txt"
        unrelated.write_text("keep")
        for _ in range(3):
            ops.backup(database, backup_dir, retain=2)
        self.assertEqual(len(list(backup_dir.glob("trader-*.sqlite3"))), 2)
        self.assertTrue(unrelated.is_file())

    def test_heartbeat_stale_invalid_and_future(self):
        heartbeat = self.root / "data/heartbeat.json"
        now = time.time()
        for stamp in (now - 181, now + 61, float("nan")):
            heartbeat.write_text(json.dumps({"timestamp": stamp}))
            self.assertTrue(ops.heartbeat_is_stale(heartbeat, 180, now=now))
        heartbeat.write_text('{"timestamp":')
        self.assertTrue(ops.heartbeat_is_stale(heartbeat, 180, now=now))
        heartbeat.write_text(json.dumps({"timestamp": now}))
        self.assertFalse(ops.heartbeat_is_stale(heartbeat, 180, now=now))
        os.utime(heartbeat, (now - 181, now - 181))
        self.assertTrue(ops.heartbeat_is_stale(heartbeat, 180, now=now))

    def test_health_does_not_restart_manually_stopped_worker(self):
        with patch.object(ops.subprocess, "run") as command:
            command.return_value.returncode = 3
            self.assertEqual(ops.health(self.root / "data", 180), 0)
            command.assert_called_once()

    def write_ready_snapshot(self, now, *, heartbeat_changes=None, ledger_changes=None):
        heartbeat = {"timestamp": now, "state": "RUNNING", "mode": "paper", "equity": 10000.0}
        ledger = {"last_cycle_ms": round(now * 1000), "status": "RUNNING", "mode": "paper", "equity": 10000.0, "halted": False, "last_error": ""}
        heartbeat.update(heartbeat_changes or {})
        ledger.update(ledger_changes or {})
        (self.root / "data/heartbeat.json").write_text(json.dumps(heartbeat), encoding="utf-8")
        connection = sqlite3.connect(self.root / "data/trader.sqlite3")
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY, payload TEXT)")
            connection.execute("INSERT OR REPLACE INTO portfolio VALUES (1, ?)", (json.dumps(ledger),))
            connection.commit()
        finally:
            connection.close()

    def test_readiness_requires_matching_running_paper_ledger(self):
        now = round(time.time(), 3)
        self.write_ready_snapshot(now)
        result = ops.readiness(self.root / "data", 180, now=now, started_at=now - 1)
        self.assertEqual(result, {"timestamp": now, "state": "RUNNING", "mode": "paper", "equity": 10000.0})

    def test_fresh_unhealthy_heartbeat_is_not_deployment_ready(self):
        now = round(time.time(), 3)
        for state in ("HALTED", "DEGRADED", "PAUSED_RISK", "STARTING"):
            with self.subTest(state=state):
                self.write_ready_snapshot(now, heartbeat_changes={"state": state}, ledger_changes={"status": state})
                self.assertFalse(ops.heartbeat_is_stale(self.root / "data/heartbeat.json", 180, now=now))
                with self.assertRaisesRegex(RuntimeError, "running paper"):
                    ops.readiness(self.root / "data", 180, now=now)

    def test_readiness_rejects_ledger_or_heartbeat_disagreement(self):
        now = round(time.time(), 3)
        cases = [
            ({"mode": "live"}, {}),
            ({}, {"mode": "live"}),
            ({}, {"status": "DEGRADED"}),
            ({}, {"halted": True}),
            ({}, {"last_error": "FeedError"}),
            ({}, {"last_cycle_ms": round(now * 1000) - 15000}),
            ({}, {"equity": 9990.0}),
            ({"equity": float("nan")}, {}),
        ]
        for heartbeat, ledger in cases:
            with self.subTest(heartbeat=heartbeat, ledger=ledger):
                self.write_ready_snapshot(now, heartbeat_changes=heartbeat, ledger_changes=ledger)
                with self.assertRaises(RuntimeError):
                    ops.readiness(self.root / "data", 180, now=now)

    def test_readiness_rejects_snapshot_from_before_current_service(self):
        now = round(time.time(), 3)
        self.write_ready_snapshot(now - 5)
        with self.assertRaisesRegex(RuntimeError, "since this service start"):
            ops.readiness(self.root / "data", 180, now=now, started_at=now - 2)

    def test_readiness_does_not_create_missing_ledger(self):
        now = round(time.time(), 3)
        self.write_ready_snapshot(now)
        database = self.root / "data/trader.sqlite3"
        database.unlink()
        with self.assertRaisesRegex(RuntimeError, "does not exist"):
            ops.readiness(self.root / "data", 180, now=now)
        self.assertFalse(database.exists())

    def test_verify_rejects_inactive_worker(self):
        with patch.object(ops.subprocess, "run") as command:
            command.return_value.returncode = 3
            with self.assertRaisesRegex(RuntimeError, "inactive"):
                ops.verify(self.root / "data", 180)
            command.assert_called_once()

    def test_no_database_means_no_empty_backup(self):
        self.assertIsNone(ops.backup(self.root / "data/missing.sqlite3", self.root / "backups"))
        self.assertFalse((self.root / "backups").exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
