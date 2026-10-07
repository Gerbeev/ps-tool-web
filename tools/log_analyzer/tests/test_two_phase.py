"""Two-stage inventory/enrichment guarantees for local fixtures (no live SMB)."""
from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze


class TwoPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.root = self.home / "Logs"
        self.cob = "20261005"
        self.file = self.root / self.cob / "Downstream" / "jobs" / "abc.log"
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"2026-10-06 01:00:00 [1] INFO : Begin\n")
        self.output = self.home / "output"
        self.report = self.output / "PROD" / self.cob / "jobs.csv"
        self.state = self.output / "PROD" / ".state" / f"{self.cob}.json"
        self.now = datetime(2026, 10, 7, tzinfo=timezone.utc)

    def run_mode(self, mode="inventory", now=None, force=False):
        stdout, stderr = StringIO(), StringIO()
        result = analyze.write_csv(
            root=self.root, output_dir=self.output, environment="PROD",
            encoding="utf-8-sig", only_date=None, delimiter=",",
            stdout=stdout, stderr=stderr, mode=mode, force=force,
            now=now or self.now,
        )
        return result, stdout.getvalue(), stderr.getvalue()

    def rows(self):
        with self.report.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))

    def test_inventory_never_opens_source_contents_and_produces_row(self):
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("source read")), \
             patch.object(analyze, "_analyze_stream", side_effect=AssertionError("parsed")):
            result, stdout, _ = self.run_mode()
        self.assertEqual(result[0], 1)
        self.assertIn("opened log contents 0", stdout)
        row = self.rows()[0]
        self.assertEqual(row["system"], "Downstream")
        self.assertEqual(row["path"], str(self.file))
        self.assertEqual(int(row["file_size_bytes"]), self.file.stat().st_size)
        self.assertEqual(row["enrichment_status"], "Pending")
        self.assertEqual(row["job_status"], "Unknown")
        self.assertEqual(row["error_count"], "")
        self.assertEqual(row["duration"], "")
        self.assertTrue(row["last_modified_time"])
        self.assertEqual(json.loads(self.state.read_text())["status"], "open")

    def test_csv_temporal_fields_use_one_format_without_iso_timezone_suffix(self):
        self.run_mode("enrich")
        row = self.rows()[0]
        self.assertEqual(row["job_date"], "2026-10-05")
        self.assertEqual(row["start_time"], "2026-10-06 01:00:00.000")
        self.assertEqual(row["end_time"], "2026-10-06 01:00:00.000")
        for field in ("last_modified_time", "start_time", "end_time", "enriched_at_utc"):
            value = row[field]
            self.assertRegex(value, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$")
            self.assertNotIn("T", value)
            self.assertNotRegex(value, r"(?:Z|[+-]\d{2}:\d{2})$")

    def test_csv_header_places_activity_status_before_path_at_end(self):
        self.run_mode()
        with self.report.open("r", encoding="utf-8-sig", newline="") as file:
            header = next(csv.reader(file))
        self.assertEqual(tuple(header), analyze.CSV_FIELDS)
        self.assertEqual(header[-2:], ["activity_status", "path"])
        self.assertNotIn("relative_path", header)

    def test_old_csv_header_is_migrated_without_source_content_read(self):
        self.run_mode()
        rows = self.rows()
        legacy_fields = ["relative_path" if field == "path" else field for field in analyze.CSV_FIELDS]
        legacy_fields.remove("activity_status")
        legacy_fields.insert(4, "activity_status")
        with self.report.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=legacy_fields)
            writer.writeheader()
            for row in rows:
                legacy = dict(row)
                legacy["relative_path"] = legacy.pop("path")
                writer.writerow({field: legacy.get(field, "") for field in legacy_fields})
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("source read")):
            result, _, _ = self.run_mode()
        self.assertEqual(result[0], 0)
        with self.report.open("r", encoding="utf-8-sig", newline="") as file:
            header = next(csv.reader(file))
        self.assertEqual(header[-2:], ["activity_status", "path"])
        self.assertEqual(self.rows()[0]["path"], str(self.file))

    def test_inventory_no_op_does_not_rewrite_report_or_state(self):
        self.run_mode()
        csv_before = self.report.stat().st_mtime_ns
        state_before = self.state.stat().st_mtime_ns
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("source read")):
            result, _, _ = self.run_mode()
        self.assertEqual(result[0], 0)
        self.assertEqual(self.report.stat().st_mtime_ns, csv_before)
        self.assertEqual(self.state.stat().st_mtime_ns, state_before)

    def test_inventory_then_enrich_only_pending_then_cached(self):
        self.run_mode()
        with patch.object(analyze, "stable_summary", wraps=analyze.stable_summary) as scanned:
            result, _, _ = self.run_mode("enrich")
            self.assertEqual(scanned.call_count, 1)
        self.assertEqual(result[0], 1)
        self.assertEqual(self.rows()[0]["enrichment_status"], "Enriched")
        self.assertEqual(self.rows()[0]["start_time"], "2026-10-06 01:00:00.000")
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("no reread")):
            result, _, _ = self.run_mode("enrich")
        self.assertEqual(result[0], 0)

    def test_inventory_detects_append_then_enrich_uses_suffix_checkpoint(self):
        self.run_mode("enrich")
        with self.file.open("ab") as f:
            f.write(b"2026-10-07 01:00:00 [2] ERROR : Finished\n")
        # inventory must not reopen this log, even though it has changed
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("source read")):
            self.run_mode("inventory")
        stale = self.rows()[0]
        self.assertEqual(stale["enrichment_status"], "Stale")
        self.assertEqual(stale["error_count"], "")
        with patch.object(analyze, "stable_summary", side_effect=AssertionError("full reparse")):
            result, stdout, _ = self.run_mode("enrich")
        self.assertEqual(result[0], 1)
        self.assertIn("suffix scans 1", stdout)
        row = self.rows()[0]
        self.assertEqual(row["error_count"], "1")
        self.assertEqual(row["duration"], "24:00:00")
        self.assertEqual(row["enrichment_status"], "Enriched")

    def test_rewrite_same_size_cannot_reuse_old_checkpoint(self):
        self.run_mode("enrich")
        data = self.file.read_bytes()
        self.file.write_bytes(data.replace(b"INFO", b"WARN"))
        os.utime(self.file, None)
        self.run_mode("inventory")
        self.assertEqual(self.rows()[0]["enrichment_status"], "Stale")
        _, stdout, _ = self.run_mode("enrich")
        self.assertIn("full scans 1", stdout)
        self.assertEqual(self.rows()[0]["warning_count"], "1")

    def test_enrich_fails_safely_and_leaves_pending(self):
        self.run_mode("inventory")
        with patch.object(analyze, "open_shared_log", side_effect=OSError("temporary SMB error")):
            result, _, err = self.run_mode("enrich")
        self.assertEqual(result[1], 1)
        self.assertIn("temporary SMB error", err)
        self.assertEqual(self.rows()[0]["enrichment_status"], "Pending")
        self.assertEqual(json.loads(self.state.read_text())["status"], "open")

    def test_inventory_does_not_finalize_old_cob_without_enrich(self):
        old_time = datetime(2026, 10, 6, tzinfo=timezone.utc).timestamp()
        os.utime(self.file, (old_time, old_time))
        late = datetime(2026, 10, 20, tzinfo=timezone.utc)
        self.run_mode("inventory", now=late)
        self.assertEqual(json.loads(self.state.read_text())["status"], "open")
        self.run_mode("enrich", now=late)
        self.assertEqual(json.loads(self.state.read_text())["status"], "closed")
        with patch.object(analyze, "iter_log_files", side_effect=AssertionError("closed traversal")):
            self.run_mode("inventory", now=late)

    def test_multiple_logs_same_name_distinguished_by_path(self):
        other = self.root / self.cob / "Upstream" / "abc.log"
        other.parent.mkdir()
        other.write_bytes(b"2026-10-06 02:00:00 [1] INFO : Started\n")
        self.run_mode("inventory")
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual({r["path"] for r in self.rows()},
                         {str(self.file), str(other)})

    def test_legacy_enriched_state_reused_as_enriched(self):
        self.run_mode("enrich")
        state = json.loads(self.state.read_text())
        for entry in state["files"].values():
            entry["row"]["relative_path"] = entry["row"].pop("path")
            entry["row"].pop("enrichment_status")
            entry["row"].pop("file_size_bytes")
            entry["row"].pop("enriched_at_utc")
            entry.pop("parsed_signature")
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("reread")):
            self.run_mode("inventory")
            self.run_mode("enrich")
        self.assertEqual(self.rows()[0]["enrichment_status"], "Enriched")

    def test_cli_defaults_to_inventory(self):
        config = self.home / "cfg.json"
        config.write_text(json.dumps({"encoding": "utf-8-sig", "environments": {
            "PROD": {"logs_root": str(self.root)}
        }}), encoding="utf-8")
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("source read")):
            code = analyze.main(["--config", str(config), "--output-dir", str(self.output),
                                 "--env", "PROD"])
        self.assertEqual(code, 0)
        self.assertEqual(self.rows()[0]["enrichment_status"], "Pending")


if __name__ == "__main__":
    unittest.main()
