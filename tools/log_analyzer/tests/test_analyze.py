"""Isolated tests: python -m unittest discover -s tools/log_analyzer/tests -v"""

import csv
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze import (  # noqa: E402
    analyze_log,
    business_date_from_path,
    excel_safe,
    format_duration,
    main,
    source_metadata_from_path,
)


class LogAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        self.logs_root = self.tmpdir / "Logs"
        self.day_dir = self.logs_root / "20261002" / "Downstream"
        self.day_dir.mkdir(parents=True)
        self.log = self.day_dir / "IB_CT_CVA_1109_P1_DS_FG_OTCC_DMOReport_Frtb.log"
        self.log.write_text(
            "2026-10-05 00:01:01,993 [1] INFO : Feed Generator version: 264.10\n"
            "2026-10-05 00:01:04,904 [1] INFO : Loading settings\n"
            "2026-10-05 00:01:05,856 [1] WARN : Could not fully resolve the following settings\n"
            "  ERROR and WARN inside a continuation should not be counted\n"
            "2026-10-05 00:05:01,993 [1] INFO : Feed Generator version: 264.10\n"
            "2026-10-05 00:09:15,001 [2] ERROR : Could not load config\n"
            "2026-10-05 00:15:15,001 [2] WARN : Retry attempt\n"
            "2026-10-05 00:20:05,901 [2] ERROR : Final error, something failed\n"
            "Stack trace without timestamp\n"
            "2026-10-05 01:11:34,993 [1] INFO : Finished\n",
            encoding="utf-8",
        )
        self.config = self.tmpdir / "config.json"
        self.config.write_text(
            json.dumps({"encoding": "utf-8-sig", "environments": {
                "PROD": {"logs_root": str(self.logs_root)},
                "U5": {"logs_root": ""},
            }}),
            encoding="utf-8",
        )
        self.output_root = self.tmpdir / "output"
        self.csv_path = self.output_root / "PROD" / "20261002" / "jobs.csv"

    def run_cli(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config), "--output-dir", str(self.output_root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_date_name_runtime_counts_and_last_error(self):
        summary = analyze_log(self.log, "20261002")
        self.assertEqual(summary.job_date, "20261002")
        self.assertEqual(summary.system, "")  # Direct API call has no source root.
        self.assertEqual(summary.job_name, "IB_CT_CVA_1109_P1_DS_FG_OTCC_DMOReport_Frtb")
        self.assertEqual(summary.job_status, "Completed")
        self.assertEqual(summary.start_time, "2026-10-05 00:01:01.993")
        self.assertEqual(summary.end_time, "2026-10-05 01:11:34.993")
        self.assertEqual(summary.duration, "01:10:33")
        self.assertEqual(summary.restart_count, 1)
        self.assertEqual(summary.warning_count, 2)
        self.assertEqual(summary.error_count, 2)
        self.assertTrue(summary.last_error.startswith("2026-10-05 00:20:05,901"))
        self.assertTrue(summary.last_error.endswith("ERROR : Final error, something failed"))

    def test_timestamp_variants_and_timestamp_only_boundary_lines(self):
        self.log.write_text(
            "2026/08/01 07:44:57:678 job started\n"
            "2026-08-01 07:45:00,001 [1] WARN : warning\n"
            "2026.08.01 08:00:03.004 job finished\n",
            encoding="utf-8",
        )
        summary = analyze_log(self.log, "20261002")
        self.assertEqual(summary.start_time, "2026-08-01 07:44:57.678")
        self.assertEqual(summary.end_time, "2026-08-01 08:00:03.004")
        self.assertEqual(summary.duration, "00:15:05")
        self.assertEqual(summary.warning_count, 1)

    def test_mixed_date_separators_are_accepted(self):
        self.log.write_text(
            "2026/08-01 07:44:57,678 [1] INFO : Start\n"
            "2026-08/01 07:44:58:679 [1] ERROR : End\n",
            encoding="utf-8",
        )
        summary = analyze_log(self.log, "20261002")
        self.assertEqual(summary.start_time, "2026-08-01 07:44:57.678")
        self.assertEqual(summary.end_time, "2026-08-01 07:44:58.679")
        self.assertEqual(summary.error_count, 1)

    def test_timestamp_model_cascade_supports_prefix_compact_dmy_and_month_names(self):
        cases = [
            (
                "[worker-7] | 2026-08-01T07:44:57.678+02:00 INFO : Start\n"
                "[worker-7] | 2026-08-01T07:45:00.001+02:00 INFO : End\n",
                "2026-08-01 07:44:57.678", "2026-08-01 07:45:00.001",
            ),
            (
                "20260801_074457.678 INFO : Start\n"
                "20260801-074500,001 WARN : End\n",
                "2026-08-01 07:44:57.678", "2026-08-01 07:45:00.001",
            ),
            (
                "01/08/2026 07:44:57,678 INFO : Start\n"
                "01.08.2026 07:45:00.001 ERROR : End\n",
                "2026-08-01 07:44:57.678", "2026-08-01 07:45:00.001",
            ),
            (
                "01-Aug-2026 07:44:57.678 INFO : Start\n"
                "August 01, 2026 07:45:00.001 INFO : End\n",
                "2026-08-01 07:44:57.678", "2026-08-01 07:45:00.001",
            ),
        ]
        for index, (content, expected_start, expected_end) in enumerate(cases):
            with self.subTest(index=index):
                self.log.write_text(content, encoding="utf-8")
                summary = analyze_log(self.log, "20261002")
                self.assertEqual(summary.start_time, expected_start)
                self.assertEqual(summary.end_time, expected_end)
                self.assertEqual(summary.duration, "00:00:02")

    def test_unicode_encoding_is_detected_per_log_file(self):
        content = (
            "2026-08-01 07:44:57,678 INFO : Start\n"
            "2026-08-01 07:45:00,001 INFO : End\n"
        )
        for encoding, payload in (
            ("utf-16", content.encode("utf-16")),
            ("utf-16-le-no-bom", content.encode("utf-16-le")),
        ):
            with self.subTest(encoding=encoding):
                self.log.write_bytes(payload)
                summary = analyze_log(self.log, "20261002", encoding="utf-8-sig")
                self.assertEqual(summary.start_time, "2026-08-01 07:44:57.678")
                self.assertEqual(summary.end_time, "2026-08-01 07:45:00.001")

    def test_timestamp_timezone_and_ampm_affect_duration_but_not_csv_format(self):
        self.log.write_text(
            "2026-08-01 11:30:00 PM +02:00 INFO : Start\n"
            "2026-08-02 12:30:00 AM +01:00 INFO : End\n",
            encoding="utf-8",
        )
        summary = analyze_log(self.log, "20261002")
        self.assertEqual(summary.start_time, "2026-08-01 23:30:00.000")
        self.assertEqual(summary.end_time, "2026-08-02 00:30:00.000")
        self.assertEqual(summary.duration, "02:00:00")

    def test_recurse_filter_uppercase_extension_excel_safe_csv(self):
        sibling = self.logs_root / "20260930" / "Other"
        sibling.mkdir(parents=True)
        (sibling / "=DANGEROUS.LOG").write_text(
            "2026-09-30 23:59:59 [7] INFO : Start\n", encoding="utf-8"
        )
        code, stdout, _ = self.run_cli("--env", "PROD", "--delimiter", ";", "--mode", "enrich")
        self.assertEqual(code, 0)
        self.assertIn("Processed: 2", stdout)
        other_report = self.output_root / "PROD" / "20260930" / "jobs.csv"
        with other_report.open("r", encoding="utf-8-sig", newline="") as stream:
            other_rows = list(csv.DictReader(stream, delimiter=";"))
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            day_rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(len(other_rows), 1)
        self.assertEqual(len(day_rows), 1)
        self.assertEqual(other_rows[0]["job_name"], "'=DANGEROUS")
        self.assertEqual(other_rows[0]["system"], "Other")
        self.assertEqual(day_rows[0]["system"], "Downstream")
        self.assertEqual(day_rows[0]["duration"], "01:10:33")
        self.assertIn("COB reports: 2", stdout)
        previous_other = other_report.read_bytes()
        self.log.write_text("2026-10-05 00:00:00 [1] INFO : Updated\n", encoding="utf-8")
        code, stdout, _ = self.run_cli("--env", "PROD", "--date", "20261002", "--mode", "enrich")
        self.assertEqual(code, 0)
        self.assertIn("Processed: 1", stdout)
        self.assertIn("COB reports: 1", stdout)
        self.assertEqual(other_report.read_bytes(), previous_other)
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            updated = list(csv.DictReader(stream))
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["duration"], "00:00:00")

    def test_separate_environments_do_not_overwrite_each_other(self):
        code, _, _ = self.run_cli("--env", "PROD")
        self.assertEqual(code, 0)
        original = self.csv_path.read_bytes()
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["environments"]["U5"]["logs_root"] = str(self.logs_root)
        self.config.write_text(json.dumps(config), encoding="utf-8")
        code, _, _ = self.run_cli("--env", "U5")
        self.assertEqual(code, 0)
        self.assertEqual(original, self.csv_path.read_bytes())
        self.assertTrue((self.output_root / "U5" / "20261002" / "jobs.csv").exists())

    def test_missing_root_is_reported_and_existing_csv_preserved(self):
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path.write_text("existing", encoding="utf-8")
        code, _, error = self.run_cli("--env", "U5")
        self.assertEqual(code, 1)
        self.assertIn("logs_root is not configured", error)
        self.assertEqual(self.csv_path.read_text(encoding="utf-8"), "existing")

    def test_no_matching_logs_does_not_replace_output(self):
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path.write_text("existing", encoding="utf-8")
        code, _, error = self.run_cli("--env", "PROD", "--date", "20261003")
        self.assertEqual(code, 1)
        self.assertIn("No logs", error)
        self.assertEqual(self.csv_path.read_text(encoding="utf-8"), "existing")

    def test_same_date_multiple_log_files_create_one_report_without_extra_bom(self):
        nested = self.logs_root / "20261002" / "Other"
        nested.mkdir(parents=True)
        (nested / "second.log").write_text(
            "2026-10-06 11:00:00 [1] INFO : Started\n", encoding="utf-8"
        )
        code, stdout, _ = self.run_cli("--env", "PROD")
        self.assertEqual(code, 0)
        self.assertIn("COB reports: 1", stdout)
        raw = self.csv_path.read_bytes()
        self.assertEqual(raw.count(b"\xef\xbb\xbf"), 1)
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["job_name"] for r in rows}, {
            self.log.stem, "second"
        })
        self.assertEqual({r["system"] for r in rows}, {"Downstream", "Other"})

    def test_system_is_cob_child_folder_even_for_nested_logs(self):
        nested_dir = self.day_dir / "Region" / "Batch"
        nested_dir.mkdir(parents=True)
        (nested_dir / "nested.log").write_text(
            "2026-10-05 00:01:01 [1] INFO : Nested\n", encoding="utf-8"
        )
        (self.logs_root / "20261002" / "root_job.log").write_text(
            "2026-10-05 00:01:01 [1] INFO : Root\n", encoding="utf-8"
        )
        code, _, _ = self.run_cli("--env", "PROD")
        self.assertEqual(code, 0)
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = {row["job_name"]: row for row in csv.DictReader(stream)}
        self.assertEqual(rows["nested"]["system"], "Downstream")
        self.assertEqual(rows["root_job"]["system"], "")
        self.assertEqual(rows[self.log.stem]["system"], "Downstream")
        self.assertEqual(list(rows["nested"])[0:3], ["job_date", "system", "job_name"])

    def test_nearest_valid_cob_and_system_from_source_path(self):
        path = self.logs_root / "20261001" / "Archive" / "20261002" / "Upstream" / "job.log"
        self.assertEqual(source_metadata_from_path(path, self.logs_root), ("20261002", "Upstream"))
        self.assertEqual(source_metadata_from_path(
            self.logs_root / "20261002" / "job.log", self.logs_root
        ), ("20261002", ""))
        self.assertEqual(source_metadata_from_path(
            self.logs_root / "folder" / "job.log", self.logs_root
        ), (None, ""))

    def test_system_csv_formula_injection_is_escaped(self):
        bad_dir = self.logs_root / "20261002" / "=1+1"
        bad_dir.mkdir(parents=True)
        (bad_dir / "file.log").write_text(
            "2026-10-05 00:01:01 [1] INFO : Start\n", encoding="utf-8"
        )
        code, _, _ = self.run_cli("--env", "PROD")
        self.assertEqual(code, 0)
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = {row["job_name"]: row for row in csv.DictReader(stream)}
        self.assertEqual(rows["file"]["system"], "'=1+1")

    def test_non_cob_root_files_are_ignored(self):
        (self.logs_root / "orphan.log").write_text("No date folder\n", encoding="utf-8")
        code, stdout, stderr = self.run_cli("--env", "PROD")
        self.assertEqual(code, 0)
        self.assertIn("Processed: 1", stdout)
        self.assertNotIn("SKIP: no valid YYYYMMDD parent folder", stderr)
        self.assertTrue(self.csv_path.exists())

    def test_empty_log_has_empty_times_no_false_restarts(self):
        empty = self.day_dir / "empty.log"
        empty.write_text("unstructured text\n", encoding="utf-8")
        summary = analyze_log(empty, "20261002")
        self.assertEqual(summary.duration, "")
        self.assertEqual(summary.start_time, "")
        self.assertEqual(summary.end_time, "")
        self.assertEqual(summary.restart_count, 0)
        self.assertEqual(summary.error_count, 0)

    def test_cross_midnight_long_hours(self):
        self.log.write_text(
            "2026-10-05 23:00:00 [1] INFO : Start\n"
            "2026-10-07 01:00:01 [1] INFO : Finish\n",
            encoding="utf-8",
        )
        summary = analyze_log(self.log, "20261002")
        self.assertEqual(summary.duration, "26:00:01")
        self.assertEqual(format_duration(90061), "25:01:01")

    def test_date_extraction_uses_folder_not_timestamp(self):
        self.assertEqual(business_date_from_path(self.log, self.logs_root), "20261002")
        self.assertIsNone(business_date_from_path(self.logs_root / "no_date" / "job.log", self.logs_root))
        self.assertEqual(excel_safe("=1+1"), "'=1+1")
        self.assertEqual(excel_safe("IB_CT_CVA_1109"), "IB_CT_CVA_1109")


if __name__ == "__main__":
    unittest.main()
