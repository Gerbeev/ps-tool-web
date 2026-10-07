"""End-to-end menu tests without any dependency on real network shares."""

import csv
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze  # noqa: E402
import menu  # noqa: E402


class MenuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.logs = self.work / "Logs" / "20261002" / "Nested"
        self.logs.mkdir(parents=True)
        (self.logs / "IB_CT_CVA_4321_U5_Load.log").write_text(
            "2026-10-06 00:00:00,123 [1] INFO : Start job\n"
            "2026-10-06 00:00:02,123 [1] WARN : Warning\n"
            "2026-10-06 00:00:09,123 [1] ERROR : Error\n"
            "2026-10-06 00:01:00,123 [1] INFO : Finished\n",
            encoding="utf-8",
        )
        self.source = self.work / "config.json"
        self.source.write_text(json.dumps({
            "encoding": "utf-8-sig",
            "environments": {
                "PROD": {"logs_root": "", "description": "Production"},
                "U5": {"logs_root": str(self.logs.parents[1]), "description": "UAT"},
            },
        }), encoding="utf-8")
        self.output = self.work / "out"

    def session(self, *answers):
        selections = iter(answers)
        stdout = StringIO()
        stderr = StringIO()
        prompts = []

        def read(prompt):
            prompts.append(prompt)
            return next(selections)

        app = menu.ConsoleMenu(read=read, output=stdout,
                               config_path=self.source)
        with patch.object(analyze, "DEFAULT_OUTPUT_DIR", self.output), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status = app.run()
        return status, stdout.getvalue(), stderr.getvalue(), prompts

    def test_exit(self):
        status, output, _, _ = self.session("0")
        self.assertEqual(status, 0)
        self.assertIn("1. Inventory logs (metadata only)", output)
        self.assertIn("2. Enrich reports (parse log contents)", output)
        self.assertIn("9. Settings", output)
        self.assertIn("Goodbye.", output)

    def test_select_confirm_parse_and_output_csv(self):
        status, output, _, prompts = self.session("2", "2", "y", "", "0")
        self.assertEqual(status, 0)
        self.assertIn("Enrichment completed successfully.", output)
        self.assertIn("Processed: 1", output)
        self.assertIn("COB reports: 1", output)
        self.assertIn("Start enrichment? [y/N]: ", prompts)
        with (self.output / "U5" / "20261002" / "jobs.csv").open("r", encoding="utf-8-sig", newline="") as stream:
            result = next(csv.DictReader(stream))
        self.assertEqual(result["job_date"], "20261002")
        self.assertEqual(result["system"], "Nested")
        self.assertEqual(result["job_status"], "Completed")
        self.assertEqual(result["job_name"], "IB_CT_CVA_4321_U5_Load")
        self.assertEqual(result["duration"], "00:01:00")
        self.assertEqual(result["warning_count"], "1")
        self.assertEqual(result["error_count"], "1")

    def test_menu_inventory_creates_metadata_without_reading_contents(self):
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("unexpected content read")):
            status, output, _, prompts = self.session("1", "2", "yes", "", "0")
        self.assertEqual(status, 0)
        self.assertIn("Inventory completed successfully.", output)
        self.assertIn("Start inventory? [y/N]: ", prompts)
        with (self.output / "U5" / "20261002" / "jobs.csv").open(encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["enrichment_status"], "Pending")
        self.assertEqual(row["error_count"], "")

    def test_cancel_is_safe_does_not_overwrite(self):
        self.output.mkdir(parents=True)
        target = self.output / "U5" / "20261002" / "jobs.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("previous report", encoding="utf-8")
        _, output, _, _ = self.session("1", "U5", "n", "0")
        self.assertIn("Parsing cancelled.", output)
        self.assertEqual(target.read_text(encoding="utf-8"), "previous report")

    def test_missing_path_prevents_parse(self):
        _, output, _, _ = self.session("1", "PROD", "0")
        self.assertIn("No log path configured", output)
        self.assertFalse((self.output / "PROD" / "20261002" / "jobs.csv").exists())

    def test_settings_save_directly_to_config_json(self):
        before = self.source.read_bytes()
        _, output, _, _ = self.session("9", "1", "PROD", str(self.logs.parents[1]), "0", "1", "1", "y", "", "0")
        self.assertNotEqual(self.source.read_bytes(), before)
        config = menu.read_config(self.source)
        self.assertEqual(config["environments"]["PROD"]["logs_root"], str(self.logs.parents[1]))
        self.assertIn("Settings saved:", output)
        self.assertTrue((self.output / "PROD" / "20261002" / "jobs.csv").exists())

    def test_change_encoding_and_description_for_approved_environment(self):
        _, output, _, _ = self.session(
            "9", "2", "U5", "Test environment",
            "3", "utf-8", "0", "0",
        )
        self.assertIn("Settings saved:", output)
        config = menu.read_config(self.source)
        self.assertEqual(config["environments"]["U5"]["description"], "Test environment")
        self.assertEqual(config["encoding"], "utf-8")

    def test_settings_reject_invalid_environment_and_encoding(self):
        _, output, _, _ = self.session("9", "1", "P1", "3", "bad-encoding", "0", "0")
        self.assertIn("Invalid environment selection.", output)
        self.assertIn("Unknown text encoding.", output)
        self.assertNotIn("Add environment", output)
        self.assertNotIn("incremental", menu.read_config(self.source))

    def test_invalid_root_reports_failure_without_crash(self):
        bad_config = menu.read_config(self.source)
        bad_config["environments"]["U5"]["logs_root"] = str(self.work / "missing")
        menu.save_config(bad_config, destination=self.source)
        _, output, stderr, _ = self.session("1", "U5", "yes", "", "0")
        self.assertIn("Parsing failed.", output)
        self.assertIn("Logs directory does not exist", stderr)

    def test_change_incremental_settings_from_menu(self):
        _, out, _, _ = self.session("9", "4", "10", "5", "96", "0", "0")
        config = menu.read_config(self.source)
        self.assertEqual(config["incremental"], {"min_active_days": 10, "quiet_hours": 96})
        self.assertIn("Minimum active COB days", out)
        self.assertIn("Quiet hours before COB finalization", out)

    def test_settings_accepts_cob_scan_limit(self):
        _, out, _, _ = self.session("9", "8", "9", "0", "0")
        config = menu.read_config(self.source)
        self.assertEqual(config["incremental"]["cob_scan_limit"], 9)
        self.assertIn("Latest COB folders to scan", out)

    def test_settings_accepts_bounded_smb_readers(self):
        config_path = self.work / "input.json"
        config_path.write_text(json.dumps({
            "encoding": "utf-8-sig", "environments": {"PROD": {"logs_root": str(self.logs.parents[1])}}
        }))
        answers = iter(["9", "7", "6", "0", "0"])
        output = StringIO()
        app = menu.ConsoleMenu(read=lambda _: next(answers), output=output,
                                       config_path=config_path)
        self.assertEqual(app.run(), 0)
        self.assertEqual(json.loads(config_path.read_text())["incremental"]["read_workers"], 6)

    def test_invalid_json_preflight_detected(self):
        self.source.write_text("broken json", encoding="utf-8")
        self.assertRaises(json.JSONDecodeError, menu.read_config, self.source)
        with patch.object(menu, "BASE_CONFIG", self.source):
            err = StringIO()
            with redirect_stderr(err):
                code = menu.main(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("Invalid config", err.getvalue())


if __name__ == "__main__":
    unittest.main()
