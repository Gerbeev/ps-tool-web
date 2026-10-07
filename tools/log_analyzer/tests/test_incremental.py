"""Deterministic incremental-COB behavior tests; no real network access."""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze


class IncrementalCobTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        self.root = self.work / "Logs"
        self.envdir = self.work / "output" / "PROD"
        self.cob = "20261005"
        self.folder = self.root / self.cob / "Downstream"
        self.folder.mkdir(parents=True)
        self.first = self.folder / "a.log"
        self.second = self.folder / "b.log"
        self.first.write_text("2026-10-06 21:59:00 [1] INFO : Start\n", encoding="utf-8")
        self.second.write_text("2026-10-06 23:01:00 [1] INFO : Start\n", encoding="utf-8")
        self.csv_path = self.envdir / self.cob / "jobs.csv"
        self.state_path = self.envdir / ".state" / f"{self.cob}.json"
        self.active_time = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

    def run_scan(self, *, now=None, force=False, only_date=None, encoding="utf-8-sig", delimiter=","):
        out, err = StringIO(), StringIO()
        result = analyze.write_csv(
            root=self.root, output_dir=self.work / "output", environment="PROD",
            encoding=encoding, delimiter=delimiter, only_date=only_date,
            policy=analyze.IncrementalPolicy(7, 72),
            now=now or self.active_time, force=force, stdout=out, stderr=err,
        )
        return result, out.getvalue(), err.getvalue()

    def rows(self):
        with self.csv_path.open(encoding="utf-8-sig", newline="") as stream:
            return {row["job_name"]: row for row in csv.DictReader(stream)}

    def test_first_run_then_no_reparse_or_csv_rewrite(self):
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 2)
        self.assertIn("COB reports: 1", out)
        before = self.csv_path.stat().st_mtime_ns
        with patch.object(analyze, "analyze_log", side_effect=AssertionError("should not read log")):
            result, out, _ = self.run_scan()
        self.assertEqual(result[0], 0)
        self.assertIn("cached: 2", out)
        self.assertIn("COB reports: 0", out)
        self.assertEqual(before, self.csv_path.stat().st_mtime_ns)
        self.assertEqual(self.rows()["a"]["system"], "Downstream")

    def test_late_append_and_new_job_after_midnight(self):
        self.run_scan()
        self.first.write_text(
            "2026-10-06 21:59:00 [1] INFO : Start\n"
            "2026-10-07 04:01:30 [2] ERROR : Finish next day\n",
            encoding="utf-8",
        )
        (self.folder / "c.log").write_text(
            "2026-10-07 09:00:00 [1] WARN : Started late\n", encoding="utf-8"
        )
        with patch.object(analyze, "_analyze_stream", wraps=analyze._analyze_stream) as call:
            result, out, _ = self.run_scan()
        self.assertEqual(result[0], 2)
        self.assertEqual(call.call_count, 1)  # c.log full scan; a.log suffix-only; b.log cached
        self.assertIn("cached: 1", out)
        rows = self.rows()
        self.assertEqual(set(rows), {"a", "b", "c"})
        self.assertEqual(rows["a"]["duration"], "06:02:30")
        self.assertEqual(rows["a"]["end_time"], "2026-10-07 04:01:30.000")
        self.assertEqual(rows["c"]["warning_count"], "1")

    def test_old_quiet_cob_is_closed_and_skipped_without_traversal(self):
        old_mtime = datetime(2026, 10, 6, tzinfo=timezone.utc).timestamp()
        for path in (self.first, self.second):
            os.utime(path, (old_mtime, old_mtime))
        archive_time = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.run_scan(now=archive_time)
        self.assertEqual(json.loads(self.state_path.read_text())["status"], "closed")
        previous = self.csv_path.read_bytes()
        late = self.folder / "late.log"
        late.write_text("2026-10-17 12:00:00 [1] INFO : New\n")
        os.utime(late, (archive_time.timestamp(), archive_time.timestamp()))
        with patch.object(analyze, "iter_log_files", side_effect=AssertionError("closed COB traversed")):
            result, out, _ = self.run_scan(now=archive_time)
        self.assertEqual(result[0], 0)
        self.assertEqual(previous, self.csv_path.read_bytes())
        self.assertIn("skipped closed COBs: 1", out)
        result, out, _ = self.run_scan(now=archive_time, force=True, only_date=self.cob)
        self.assertEqual(result[0], 3)
        self.assertIn("late", self.rows())
        self.assertEqual(json.loads(self.state_path.read_text())["status"], "open")

    def test_old_cob_recent_activity_stays_open(self):
        latest = datetime(2026, 10, 16, tzinfo=timezone.utc).timestamp()
        os.utime(self.first, (latest, latest))
        self.run_scan(now=datetime(2026, 10, 17, tzinfo=timezone.utc))
        self.assertEqual(json.loads(self.state_path.read_text())["status"], "open")

    def test_delete_one_log_removes_row_but_preserves_other(self):
        self.run_scan()
        self.second.unlink()
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 0)
        self.assertIn("removed: 1", out)
        self.assertEqual(list(self.rows()), ["a"])

    def test_when_all_logs_disappear_existing_report_is_preserved(self):
        self.run_scan()
        before = self.csv_path.read_bytes()
        self.first.unlink()
        self.second.unlink()
        _, _, err = self.run_scan()
        self.assertIn("previous report preserved", err)
        self.assertEqual(before, self.csv_path.read_bytes())

    def test_network_walk_failure_keeps_csv_state_and_unlocks(self):
        self.run_scan()
        old_csv, old_state = self.csv_path.read_bytes(), self.state_path.read_bytes()
        with patch.object(analyze, "iter_log_files", side_effect=OSError("network unavailable")):
            with self.assertRaisesRegex(OSError, "network unavailable"):
                self.run_scan()
        self.assertEqual(self.csv_path.read_bytes(), old_csv)
        self.assertEqual(self.state_path.read_bytes(), old_state)
        self.assertFalse((self.envdir / ".analyzer.lock").exists())

    def test_append_during_parse_is_snapshot_not_reread_or_lock(self):
        self.run_scan()
        old = self.rows()["a"]
        self.first.write_text("2026-10-06 22:00:00 [1] INFO : Changed\n", encoding="utf-8")
        original = analyze._analyze_stream
        appended = []

        def append_during_read(stream, path, *args, **kwargs):
            outcome = original(stream, path, *args, **kwargs)
            if path == self.first and not appended:
                appended.append(True)
                with path.open("a") as writer:
                    writer.write("2026-10-07 00:00:00 [1] INFO : Progress\n")
            return outcome

        with patch.object(analyze, "_analyze_stream", side_effect=append_during_read) as call:
            result, _, err = self.run_scan()
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], 0)
        self.assertEqual(call.call_count, 1)  # no read/retry storms
        self.assertNotIn("Progress", self.rows()["a"]["end_time"])
        self.assertEqual(self.rows()["a"]["start_time"], "2026-10-06 22:00:00.000")
        result, _, _ = self.run_scan()
        self.assertEqual(result[0], 1)
        self.assertEqual(self.rows()["a"]["end_time"], "2026-10-07 00:00:00.000")

    def test_state_corruption_and_encoding_change_invalidate_cache(self):
        self.run_scan()
        self.state_path.write_text("not valid json", encoding="utf-8")
        result, _, err = self.run_scan()
        self.assertEqual(result[0], 2)
        self.assertIn("ignoring unreadable state", err)
        result, _, err = self.run_scan(encoding="utf-8")
        self.assertEqual(result[0], 2)
        self.assertIn("invalidated state", err)

    def test_failure_to_save_state_is_recoverable(self):
        with patch.object(analyze, "atomic_json", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.run_scan()
        self.assertTrue(self.csv_path.is_file())
        self.assertFalse(self.state_path.exists())
        result, _, _ = self.run_scan()
        self.assertEqual(result[0], 2)
        self.assertTrue(self.state_path.exists())

    def test_2300_jobs_are_cached_on_second_run(self):
        for i in range(2298):
            (self.folder / f"job{i:04d}.log").write_text(
                "2026-10-06 08:00:00 [1] INFO : Started\n", encoding="utf-8"
            )
        first, _, _ = self.run_scan()
        self.assertEqual(first[0], 2300)
        second, out, _ = self.run_scan()
        self.assertEqual(second[0], 0)
        self.assertIn("cached: 2300", out)
        self.assertEqual(len(self.rows()), 2300)

    def test_new_cob_discovered_while_old_cob_finalized(self):
        old_mtime = datetime(2026, 10, 6, tzinfo=timezone.utc).timestamp()
        for path in (self.first, self.second):
            os.utime(path, (old_mtime, old_mtime))
        archive_time = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.run_scan(now=archive_time)
        latest = self.root / "20261016" / "Upstream"
        latest.mkdir(parents=True)
        (latest / "newjob.log").write_text("2026-10-17 01:00:00 [1] INFO : Start\n")
        result, out, _ = self.run_scan(now=archive_time)
        self.assertEqual(result[0], 1)
        self.assertIn("skipped closed COBs: 1", out)
        self.assertTrue((self.envdir / "20261016" / "jobs.csv").is_file())
        self.assertEqual(self.csv_path.is_file(), True)

    def test_existing_lock_blocks_concurrent_run(self):
        self.envdir.mkdir(parents=True)
        lock = self.envdir / ".analyzer.lock"
        lock.write_text("busy", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already running"):
            self.run_scan()
        self.assertEqual(lock.read_text(encoding="utf-8"), "busy")

    def test_source_log_bytes_and_metadata_are_never_modified(self):
        import hashlib
        before = {
            path: (hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns)
            for path in (self.first, self.second)
        }
        self.run_scan()
        self.run_scan()
        for path, (digest, mtime_ns) in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)
            self.assertEqual(path.stat().st_mtime_ns, mtime_ns)
        self.assertFalse((self.root / ".analyzer.lock").exists())

    def test_recent_activity_transitions_without_reparsing(self):
        import time
        mtime = time.time()
        os.utime(self.first, (mtime, mtime))
        os.utime(self.second, (mtime, mtime))
        recent = datetime.fromtimestamp(mtime + 120, tz=timezone.utc)
        older = datetime.fromtimestamp(mtime + 600, tz=timezone.utc)
        self.run_scan(now=recent)
        self.assertEqual(self.rows()["a"]["activity_status"], "RecentlyModified")
        first_csv = self.csv_path.read_bytes()
        with patch.object(analyze, "_analyze_stream", side_effect=AssertionError("no reread")):
            result, out, _ = self.run_scan(now=older)
        self.assertEqual(result[0], 0)
        self.assertIn("cached: 2", out)
        self.assertEqual(self.rows()["a"]["activity_status"], "NotRecentlyModified")
        self.assertNotEqual(first_csv, self.csv_path.read_bytes())
        with patch.object(analyze, "_analyze_stream", side_effect=AssertionError("no reread")):
            _, out, _ = self.run_scan(now=older)
        self.assertIn("COB reports: 0", out)

    def test_partial_tail_is_ignored_until_writer_finishes_line(self):
        self.first.write_text(
            "2026-10-06 10:00:00 [1] INFO : Start\n"
            "2026-10-06 10:15:00 [1] ERROR : Partial",
            encoding="utf-8",
        )
        self.run_scan(now=datetime.now(timezone.utc))
        self.assertEqual(self.rows()["a"]["error_count"], "0")
        with self.first.open("a", encoding="utf-8") as writer:
            writer.write(" message\n")
        self.run_scan(now=datetime.now(timezone.utc))
        self.assertEqual(self.rows()["a"]["error_count"], "1")
        self.assertIn("Partial message", self.rows()["a"]["last_error"])

    def test_stable_log_without_terminal_newline_is_supported(self):
        import time
        self.first.write_text("2026-10-06 10:00:00 [1] ERROR : End", encoding="utf-8")
        old = time.time() - 3600
        os.utime(self.first, (old, old))
        self.run_scan()
        self.assertEqual(self.rows()["a"]["error_count"], "1")

    def test_utf16_logs_can_be_read_from_a_snapshot(self):
        self.first.write_text("2026-10-06 10:00:00 [1] INFO : Start\n", encoding="utf-16")
        self.second.write_text("2026-10-06 11:00:00 [1] INFO : Start\n", encoding="utf-16")
        self.run_scan(encoding="utf-16")
        self.assertEqual(self.rows()["a"]["start_time"], "2026-10-06 10:00:00.000")

    def test_win32_reader_requests_read_only_with_full_share_flags(self):
        import sys
        from types import SimpleNamespace
        original_open = os.open
        captured = []

        def fake_create(path, access, share, security, disposition, flags, template):
            captured.append((path, access, share, disposition))
            return original_open(path, os.O_RDONLY)

        def fake_close(handle):
            os.close(handle)

        fake_msvcrt = SimpleNamespace(open_osfhandle=lambda handle, flags: handle)
        with (patch.object(analyze.os, "name", "nt"),
              patch.object(analyze.os, "O_BINARY", 0, create=True),
              patch.object(analyze.os, "O_NOINHERIT", 0, create=True),
              patch.object(analyze, "_windows_file_api", return_value=(fake_create, fake_close)),
              patch.dict(sys.modules, {"msvcrt": fake_msvcrt})):
            with analyze.open_shared_log(self.first) as stream:
                self.assertIn(b"Start", stream.read())
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][1], 0x80000000)  # GENERIC_READ
        self.assertEqual(captured[0][2], 0x1 | 0x2 | 0x4)  # share read/write/delete
        self.assertEqual(captured[0][3], 3)  # OPEN_EXISTING (never create)

    def test_output_cannot_overlap_source_directory(self):
        with self.assertRaisesRegex(ValueError, "Output directory must be separate"):
            analyze.write_csv(
                root=self.root, output_dir=self.root, environment="PROD",
                encoding="utf-8", only_date=None, delimiter=",",
                now=self.active_time,
            )
        self.assertFalse((self.root / "PROD").exists())

    def test_existing_open_manifest_migrates_new_columns_without_reread(self):
        self.run_scan()
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for item in state["files"].values():
            del item["row"]["activity_status"]
            del item["row"]["last_modified_time"]
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(analyze, "_analyze_stream", side_effect=AssertionError("should use old index")):
            result, _, _ = self.run_scan()
        self.assertEqual(result[0], 0)
        self.assertTrue(self.rows()["a"]["last_modified_time"])

    def test_large_log_append_reads_only_new_bytes(self):
        line = b"2026-10-06 10:00:00 [1] INFO : Long running\n"
        with self.first.open("wb") as handle:
            for _ in range(70000):
                handle.write(line)
        self.run_scan()
        before = self.first.stat().st_size
        with self.first.open("ab") as handle:
            handle.write(b"2026-10-07 10:00:00 [1] ERROR : End\n")
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 1)
        self.assertIn("suffix scans 1", out)
        self.assertIn("full scans 0", out)
        self.assertIn("payload bytes scanned 36", out)
        self.assertGreater(before, 2_000_000)
        self.assertEqual(self.rows()["a"]["error_count"], "1")
        self.assertEqual(self.rows()["a"]["duration"], "24:00:00")

    def test_same_length_rewrite_forces_full_rescan(self):
        self.run_scan()
        self.first.write_text("2026-10-06 21:59:00 [1] WARN : Start\n", encoding="utf-8")
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 1)
        self.assertIn("full scans 1", out)
        self.assertEqual(self.rows()["a"]["warning_count"], "1")

    def test_truncation_forces_full_rescan(self):
        self.run_scan()
        self.first.write_text("2026-10-06 22:01:00 [1] ERROR : Changed\n", encoding="utf-8")
        self.run_scan()
        self.first.write_text("2026-10-06 12:00:00 [1] INFO : Short\n", encoding="utf-8")
        result, out, _ = self.run_scan()
        self.assertIn("full scans 1", out)
        self.assertEqual(self.rows()["a"]["error_count"], "0")

    def test_prefix_anchor_detects_rewrite_then_append(self):
        self.run_scan()
        first = self.first.read_bytes().replace(b"Start", b"Other")
        self.first.write_bytes(first + b"2026-10-07 10:00:00 [1] WARN : Next\n")
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 1)
        self.assertIn("full scans 1", out)
        self.assertEqual(self.rows()["a"]["warning_count"], "1")

    def test_utf16_incremental_append(self):
        self.first.write_text("2026-10-06 10:00:00 [1] INFO : Start\n", encoding="utf-16")
        self.second.write_text("2026-10-06 11:00:00 [1] INFO : Start\n", encoding="utf-16")
        self.run_scan(encoding="utf-16")
        with self.first.open("ab") as stream:
            stream.write("2026-10-07 10:00:00 [1] ERROR : Failure\n".encode("utf-16-le"))
        result, out, _ = self.run_scan(encoding="utf-16")
        self.assertEqual(result[0], 1)
        self.assertIn("suffix scans 1", out)
        self.assertEqual(self.rows()["a"]["duration"], "24:00:00")
        self.assertEqual(self.rows()["a"]["error_count"], "1")

    def test_utf32_incremental_append(self):
        self.first.write_text("2026-10-06 10:00:00 [1] INFO : Start\n", encoding="utf-32")
        self.second.write_text("2026-10-06 11:00:00 [1] INFO : Start\n", encoding="utf-32")
        self.run_scan(encoding="utf-32")
        with self.first.open("ab") as handle:
            handle.write("2026-10-07 10:00:00 [1] WARN : Note\n".encode("utf-32-le"))
        result, out, _ = self.run_scan(encoding="utf-32")
        self.assertEqual(result[0], 1)
        self.assertIn("suffix scans 1", out)
        self.assertEqual(self.rows()["a"]["warning_count"], "1")

    def test_unterminated_tail_aging_is_applied_once(self):
        import time
        self.first.write_text("2026-10-06 10:00:00 [1] INFO : Start\n"
                              "2026-10-06 11:00:00 [1] ERROR : Final", encoding="utf-8")
        timestamp = time.time()
        os.utime(self.first, (timestamp, timestamp))
        self.run_scan(now=datetime.fromtimestamp(timestamp + 30, timezone.utc))
        self.assertEqual(self.rows()["a"]["error_count"], "0")
        result, out, _ = self.run_scan(now=datetime.fromtimestamp(timestamp + 600, timezone.utc))
        self.assertEqual(result[0], 1)
        self.assertIn("suffix scans 1", out)
        self.assertEqual(self.rows()["a"]["error_count"], "1")
        result, _, _ = self.run_scan(now=datetime.fromtimestamp(timestamp + 630, timezone.utc))
        self.assertEqual(result[0], 0)
        self.assertEqual(self.rows()["a"]["error_count"], "1")
        with self.first.open("ab") as stream:
            stream.write(b" message\n")
        self.run_scan(now=datetime.fromtimestamp(timestamp + 700, timezone.utc))
        self.assertEqual(self.rows()["a"]["error_count"], "1")
        self.assertIn("Final message", self.rows()["a"]["last_error"])

    def test_legacy_state_migrates_without_extra_rescan(self):
        self.run_scan()
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        for item in raw["files"].values():
            item.pop("checkpoint", None)
            item.pop("anchor", None)
            item.pop("identity", None)
        self.state_path.write_text(json.dumps(raw), encoding="utf-8")
        result, _, _ = self.run_scan()
        self.assertEqual(result[0], 0)
        with self.first.open("ab") as handle:
            handle.write(b"2026-10-07 10:00:00 [1] WARN : Next\n")
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 1)
        self.assertIn("full scans 1", out)
        self.assertEqual(self.rows()["a"]["warning_count"], "1")

    def test_noop_scan_does_not_rewrite_state_or_csv(self):
        self.run_scan()
        csv_time = self.csv_path.stat().st_mtime_ns
        state_bytes = self.state_path.read_bytes()
        state_time = self.state_path.stat().st_mtime_ns
        result, out, _ = self.run_scan()
        self.assertEqual(result[0], 0)
        self.assertEqual(csv_time, self.csv_path.stat().st_mtime_ns)
        self.assertEqual(state_time, self.state_path.stat().st_mtime_ns)
        self.assertEqual(state_bytes, self.state_path.read_bytes())
        self.assertIn("payload bytes scanned 0", out)

    def test_worker_concurrency_is_bounded(self):
        import threading
        import time
        for idx in range(20):
            (self.folder / f"bulk_{idx}.log").write_text(
                "2026-10-06 10:00:00 [1] INFO : Start\n", encoding="utf-8")
        lock = threading.Lock()
        active = peak = 0
        original = analyze.parse_changed

        def controlled(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.01)
                return original(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

        with patch.object(analyze, "parse_changed", side_effect=controlled):
            result, _, _ = self.run_scan()
        self.assertEqual(result[0], 22)
        self.assertLessEqual(peak, 4)
        self.assertGreaterEqual(peak, 2)
        self.assertEqual(len(self.rows()), 22)

    def test_policy_is_validated(self):
        config = self.work / "config.json"
        config.write_text(json.dumps({"incremental": {"min_active_days": 7, "quiet_hours": 72}}))
        self.assertEqual(analyze.read_policy(config).quiet_hours, 72)
        self.assertEqual(analyze.read_policy(config).read_workers, 4)
        config.write_text(json.dumps({"incremental": {"min_active_days": True}}))
        with self.assertRaises(ValueError):
            analyze.read_policy(config)
        config.write_text(json.dumps({"incremental": {"read_workers": 17}}))
        with self.assertRaisesRegex(ValueError, "read_workers"):
            analyze.read_policy(config)


if __name__ == "__main__":
    unittest.main()
