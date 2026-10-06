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
        self.local = self.work / "config.local.json"
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
                               config_source=self.local if self.local.exists() else self.source,
                               config_destination=self.local)
        with patch.object(analyze, "DEFAULT_OUTPUT_DIR", self.output), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status = app.run()
        return status, stdout.getvalue(), stderr.getvalue(), prompts

    def test_exit(self):
        status, output, _, _ = self.session("0")
        self.assertEqual(status, 0)
        self.assertIn("1. Select environment / Parse logs", output)
        self.assertIn("9. Settings", output)
        self.assertIn("Goodbye.", output)

    def test_select_confirm_parse_and_output_csv(self):
        status, output, _, prompts = self.session("1", "2", "y", "", "0")
        self.assertEqual(status, 0)
        self.assertIn("Parsing completed successfully.", output)
        self.assertIn("Processed: 1", output)
        self.assertIn("Start parsing? [y/N]: ", prompts)
        with (self.output / "U5_jobs.csv").open("r", encoding="utf-8-sig", newline="") as stream:
            result = next(csv.DictReader(stream))
        self.assertEqual(result["job_date"], "20261002")
        self.assertEqual(result["job_status"], "Completed")
        self.assertEqual(result["job_name"], "IB_CT_CVA_4321_U5_Load")
        self.assertEqual(result["duration"], "00:01:00")
        self.assertEqual(result["warning_count"], "1")
        self.assertEqual(result["error_count"], "1")

    def test_cancel_is_safe_does_not_overwrite(self):
        self.output.mkdir(parents=True)
        target = self.output / "U5_jobs.csv"
        target.write_text("previous report", encoding="utf-8")
        _, output, _, _ = self.session("1", "U5", "n", "0")
        self.assertIn("Parsing cancelled.", output)
        self.assertEqual(target.read_text(encoding="utf-8"), "previous report")

    def test_missing_path_prevents_parse(self):
        _, output, _, _ = self.session("1", "PROD", "0")
        self.assertIn("No log path configured", output)
        self.assertFalse((self.output / "PROD_jobs.csv").exists())

    def test_settings_create_local_config_without_touching_template(self):
        before = self.source.read_bytes()
        _, output, _, _ = self.session("9", "1", "PROD", str(self.logs.parents[1]), "0", "1", "1", "y", "", "0")
        self.assertTrue(self.local.exists())
        self.assertEqual(self.source.read_bytes(), before)
        local = menu.read_config(self.local)
        self.assertEqual(local["environments"]["PROD"]["logs_root"], str(self.logs.parents[1]))
        self.assertIn("Settings saved:", output)
        self.assertTrue((self.output / "PROD_jobs.csv").exists())

    def test_add_environment_and_change_encoding_and_description(self):
        _, output, _, _ = self.session(
            "9", "3", "T2", str(self.logs.parents[1]), "Testing",
            "2", "T2", "Test environment",
            "4", "utf-8", "0", "0",
        )
        self.assertIn("Settings saved:", output)
        config = menu.read_config(self.local)
        self.assertEqual(config["environments"]["T2"]["description"], "Test environment")
        self.assertEqual(config["encoding"], "utf-8")

    def test_settings_reject_invalid_environment_and_encoding(self):
        _, output, _, _ = self.session("9", "3", "?bad", "4", "bad-encoding", "0", "0")
        self.assertIn("Use 1-16 characters", output)
        self.assertIn("Unknown text encoding.", output)
        self.assertFalse(self.local.exists())

    def test_invalid_root_reports_failure_without_crash(self):
        bad_config = menu.read_config(self.source)
        bad_config["environments"]["U5"]["logs_root"] = str(self.work / "missing")
        menu.save_local_config(bad_config, destination=self.local)
        _, output, stderr, _ = self.session("1", "U5", "yes", "", "0")
        self.assertIn("Parsing failed.", output)
        self.assertIn("Logs directory does not exist", stderr)

    def test_invalid_json_preflight_detected(self):
        self.local.write_text("broken json", encoding="utf-8")
        self.assertRaises(json.JSONDecodeError, menu.read_config, self.local)
        with patch.object(menu, "LOCAL_CONFIG", self.local):
            err = StringIO()
            with redirect_stderr(err):
                code = menu.main(["--check"])
        self.assertEqual(code, 1)
        self.assertIn("Invalid config", err.getvalue())


if __name__ == "__main__":
    unittest.main()
