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
        self.csv_path = self.tmpdir / "job_report.csv"

    def run_cli(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config), "--output", str(self.csv_path), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_date_name_runtime_counts_and_last_error(self):
        summary = analyze_log(self.log, "20261002")
        self.assertEqual(summary.job_date, "20261002")
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

    def test_recurse_filter_uppercase_extension_excel_safe_csv(self):
        sibling = self.logs_root / "20260930" / "Other"
        sibling.mkdir(parents=True)
        (sibling / "=DANGEROUS.LOG").write_text(
            "2026-09-30 23:59:59 [7] INFO : Start\n", encoding="utf-8"
        )
        code, stdout, _ = self.run_cli("--env", "PROD", "--delimiter", ";")
        self.assertEqual(code, 0)
        self.assertIn("Processed: 2", stdout)
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["job_name"], "'=DANGEROUS")
        self.assertEqual(rows[1]["duration"], "01:10:33")
        code, stdout, _ = self.run_cli("--env", "PROD", "--date", "20261002")
        self.assertEqual(code, 0)
        self.assertIn("Processed: 1", stdout)

    def test_missing_root_is_reported_and_existing_csv_preserved(self):
        self.csv_path.write_text("existing", encoding="utf-8")
        code, _, error = self.run_cli("--env", "U5")
        self.assertEqual(code, 1)
        self.assertIn("logs_root is not configured", error)
        self.assertEqual(self.csv_path.read_text(encoding="utf-8"), "existing")

    def test_no_matching_logs_does_not_replace_output(self):
        self.csv_path.write_text("existing", encoding="utf-8")
        code, _, error = self.run_cli("--env", "PROD", "--date", "20261003")
        self.assertEqual(code, 1)
        self.assertIn("No logs", error)
        self.assertEqual(self.csv_path.read_text(encoding="utf-8"), "existing")

    def test_missing_date_folder_is_skipped_with_nonzero_exit(self):
        (self.logs_root / "orphan.log").write_text("No date folder\n", encoding="utf-8")
        code, stdout, stderr = self.run_cli("--env", "PROD")
        self.assertEqual(code, 2)
        self.assertIn("Processed: 1", stdout)
        self.assertIn("SKIP: no valid YYYYMMDD parent folder", stderr)
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
