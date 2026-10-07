"""Approved environment selection and single-file configuration."""

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze  # noqa: E402
import menu  # noqa: E402


class EnvironmentTests(unittest.TestCase):
    def test_shipped_paths_use_expected_source_folders(self):
        config = menu.read_config(menu.BASE_CONFIG)
        expected = {"PROD": "PROD", "U5": "_U5", "U1": "_U1", "U6": "_U6"}
        self.assertEqual(list(config["environments"]), list(expected))
        for code, folder in expected.items():
            source = PureWindowsPath(config["environments"][code]["logs_root"])
            self.assertEqual(source.parts[-2:], (folder, "Logs"))
            self.assertEqual(source.parts[0], "\\\\ldnroot\\data\\")
            if code == "PROD":
                self.assertNotIn("UAT", source.parts)
            else:
                self.assertEqual(source.parts[-3], "UAT")

    def test_single_config_does_not_merge_paths_or_environments(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config_path = directory / "config.json"
            overrides = {
                "encoding": "utf-8-sig",
                "environments": {
                    "PROD": {"logs_root": r"C:\approved\PROD\Logs"},
                    "P1": {"logs_root": r"C:\not-allowed"},
                },
            }
            config_path.write_text(json.dumps(overrides), encoding="utf-8")
            config = menu.read_config(config_path)
            self.assertEqual(list(config["environments"]), ["PROD"])
            self.assertEqual(config["environments"]["PROD"]["logs_root"], r"C:\approved\PROD\Logs")
            self.assertEqual(analyze.resolve_root(config_path, "PROD")[0], Path(r"C:\approved\PROD\Logs") if sys.platform == "win32" else directory / r"C:\approved\PROD\Logs")
            with self.assertRaisesRegex(ValueError, "is missing"):
                analyze.resolve_root(config_path, "U6")

    def test_legacy_local_file_is_ignored_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            original = menu.BASE_CONFIG.read_text(encoding="utf-8")
            config_path = directory / "config.json"
            config_path.write_text(original, encoding="utf-8")
            (directory / "config.local.json").write_text("{broken json", encoding="utf-8")
            self.assertEqual(menu.read_config(config_path)["environments"]["U6"]["logs_root"],
                             json.loads(original)["environments"]["U6"]["logs_root"])
            self.assertEqual(analyze.DEFAULT_CONFIG.name, "config.json")
            from unittest.mock import patch
            with patch.object(menu, "BASE_CONFIG", config_path):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(menu.main(["--check"]), 0)
                self.assertIn(f"Configuration: {config_path}", output.getvalue())
            self.assertNotIn("local", output.getvalue())

    def test_unapproved_cli_environment_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            config_file = Path(temp) / "config.json"
            config_file.write_text(json.dumps({"environments": {
                "P1": {"logs_root": str(Path(temp) / "Logs")},
                "PROD": {"logs_root": str(Path(temp) / "Logs")},
            }}), encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr), redirect_stdout(StringIO()):
                status = analyze.main(["--config", str(config_file), "--env", "P1"])
            self.assertEqual(status, 1)
            self.assertIn("Unsupported environment", stderr.getvalue())

    def test_choice_list_only_contains_approved_codes(self):
        config = menu.read_config(menu.BASE_CONFIG)
        output = StringIO()
        app = menu.ConsoleMenu(read=lambda _: "P1", output=output)
        self.assertIsNone(app.choose_environment(config))
        self.assertIn("Invalid environment selection", output.getvalue())
        for code in analyze.ALLOWED_ENVIRONMENTS:
            self.assertIn(code, output.getvalue())
        self.assertNotIn("P1", output.getvalue().split("Invalid environment selection")[0])


if __name__ == "__main__":
    unittest.main()
