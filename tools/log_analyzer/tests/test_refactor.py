"""Refactor-specific regressions; all fixtures are local and deterministic."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze
import menu


class RefactorRegressions(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.root = self.home / "Logs"
        self.folder = self.root / "20261005" / "Downstream"
        self.folder.mkdir(parents=True)
        self.log = self.folder / "a.log"
        self.log.write_text("2026-10-05 10:00:00 [1] INFO : Begin\n", encoding="utf-8")
        self.output = self.home / "reports"
        self.config = self.home / "config.json"
        self.config.write_text(json.dumps({
            "environments": {"PROD": {"logs_root": str(self.root)}},
            "incremental": {"parallel_workers": 2},
        }), encoding="utf-8")
        self.now = datetime(2026, 10, 7, tzinfo=timezone.utc)

    def run_mode(self, mode: str) -> tuple[int, int, int, int]:
        return analyze.write_csv(
            root=self.root, output_dir=self.output, environment="PROD",
            encoding="utf-8-sig", only_date=None, delimiter=",", mode=mode,
            now=self.now, stdout=StringIO(), stderr=StringIO(),
        )

    def test_large_line_checkpoint_is_bounded_and_subsequent_line_is_found(self) -> None:
        self.log.write_bytes(b"noise" * (2 * 1024 * 1024) + b"\n"
                             + b"2026-10-05 10:00:00 [1] INFO : Begin\n"
                             + b"2026-10-05 11:01:00 [1] ERROR : End\n")
        result = analyze.analyze_log(self.log, "20261005")
        self.assertEqual(result.duration, "01:01:00")
        self.assertEqual(result.error_count, 1)

    def test_oversized_line_rejected_even_when_terminated(self) -> None:
        self.log.write_bytes(b"x" * (analyze.MAX_LINE_BYTES + 1) + b"\n")
        with self.assertRaisesRegex(OSError, "16 MiB"):
            analyze.analyze_log(self.log, "20261005")

    def test_utf16_and_utf32_separators_cross_chunk_boundaries(self) -> None:
        for encoding in ("utf-16", "utf-32"):
            with self.subTest(encoding=encoding), patch.object(analyze, "READ_CHUNK_BYTES", 7):
                self.log.write_text(
                    "2026-10-05 10:00:00 [1] INFO : Begin\n"
                    "2026-10-05 11:01:00 [1] ERROR : End\n", encoding=encoding,
                )
                result = analyze.analyze_log(self.log, "20261005", encoding)
                self.assertEqual(result.duration, "01:01:00")
                self.assertEqual(result.error_count, 1)

    def test_malformed_cached_state_is_rebuilt(self) -> None:
        self.run_mode("enrich")
        state_path = self.output / "PROD" / ".state" / "20261005.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["files"]["Downstream/a.log"]["signature"] = "not-a-signature"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(self.run_mode("enrich")[0], 1)
        with (self.output / "PROD" / "20261005" / "jobs.csv").open(
            encoding="utf-8-sig", newline="",
        ) as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["enrichment_status"], "Enriched")

    def test_atomic_csv_accepts_legacy_missing_and_extra_fields(self) -> None:
        path = self.home / "legacy.csv"
        analyze.atomic_csv(path, {"Downstream/a.log": {"row": {
            "system": "=malicious", "job_name": "a", "last_error": "", "future_field": "extra",
        }}}, ",")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            result = next(csv.DictReader(stream))
        self.assertEqual(result["system"], "'=malicious")
        self.assertEqual(result["enrichment_status"], "")
        self.assertNotIn("future_field", result)

    def test_cli_reuses_a_single_config_read(self) -> None:
        real = analyze.load_config
        with patch.object(analyze, "load_config", wraps=real) as load:
            self.assertEqual(analyze.main([
                "--env", "PROD", "--config", str(self.config),
                "--output-dir", str(self.output), "--no-progress",
            ]), 0)
        self.assertEqual(load.call_count, 1)

    def test_menu_and_cli_share_same_policy_validation(self) -> None:
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["incremental"]["parallel_workers"] = 99
        with self.assertRaisesRegex(ValueError, "parallel_workers"):
            analyze.validate_config(data)
        with self.assertRaisesRegex(ValueError, "parallel_workers"):
            menu.save_config(data, destination=self.config)
        self.assertEqual(json.loads(self.config.read_text())["incremental"]["parallel_workers"], 2)

    def test_reject_unsupported_env_when_called_directly(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported environment"):
            analyze.write_csv(
                root=self.root, output_dir=self.output, environment="DEV",
                encoding="utf-8", only_date=None, delimiter=",",
            )


if __name__ == "__main__":
    unittest.main()
