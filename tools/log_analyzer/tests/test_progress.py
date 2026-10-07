"""Single-screen terminal dashboard, real analyzer callbacks, and plain-text fallback."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze
from progress import ConsoleProgress, _compact_event, _fit, _safe


class FakeTTY(StringIO):
    def isatty(self) -> bool:
        return True


class ProgressScreenTests(unittest.TestCase):
    def test_dashboard_uses_same_screen_and_restores_cursor(self) -> None:
        screen = FakeTTY()
        with ConsoleProgress("PROD", "enrich", stream=screen, refresh_interval=.02) as board:
            board.discovered(3)
            board.begin_cob("20261005", 1)
            board.set_file_total(4)
            board.file_completed("cached", "Downstream/job1.log")
            board.file_completed("enriched", "Downstream/job2.log")
            board.message("CSV: written", error=False)
            time.sleep(.08)  # Background tick refreshes during lengthy parses.
            self.assertEqual(board.file_done, 2)
            self.assertEqual(board.file_total, 4)
            self.assertEqual(board.cached, 1)
            self.assertEqual(board.parsed, 1)
        output = screen.getvalue()
        self.assertTrue(output.startswith("\x1b[?1049h\x1b[?25l"))
        self.assertIn("2 / 4", output)
        self.assertIn("50.0%", output)
        self.assertIn("COB           : 20261005  (1/3)", output)
        self.assertIn("Elapsed", output)
        self.assertIn("Enriched: 1", output)
        self.assertIn("\x1b[H\x1b[2J", output)
        self.assertTrue(output.endswith("\x1b[?25h\x1b[?1049l"))

    def test_dashboard_restores_screen_after_exception(self) -> None:
        screen = FakeTTY()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with ConsoleProgress("U5", "inventory", stream=screen):
                raise RuntimeError("boom")
        self.assertTrue(screen.getvalue().endswith("\x1b[?25h\x1b[?1049l"))

    def test_messages_are_sanitized_and_bounded(self) -> None:
        board = ConsoleProgress("PROD", "inventory", stream=FakeTTY())
        for num in range(12):
            board.message(f"WARN: bad file {num}\x1b[2J", error=True)
        self.assertEqual(board.error_count, 12)
        self.assertEqual(len(board.events), 6)
        self.assertEqual(len(board.errors), 5)
        self.assertNotIn("\x1b", "".join(board.events))
        self.assertEqual(_safe("line\nnext"), "line next")

    def test_long_running_reader_refreshes_with_no_file_completion(self) -> None:
        screen = FakeTTY()
        with ConsoleProgress("PROD", "enrich", stream=screen, refresh_interval=.015) as board:
            board.discovered(1)
            board.begin_cob("20261005", 1)
            board.set_file_total(2)
            board.file_queued("Downstream/very_large.log")
            time.sleep(.09)
            self.assertIn("Queued reads: 1", screen.getvalue())
            self.assertGreaterEqual(screen.getvalue().count("\x1b[H\x1b[2J"), 2)
            board.file_completed("enriched", "Downstream/very_large.log")
            self.assertEqual(len(board.in_flight), 0)

    def test_non_tty_does_not_emit_ansi(self) -> None:
        screen = StringIO()
        with ConsoleProgress("PROD", "inventory", stream=screen) as board:
            self.assertFalse(board.enabled)
        self.assertEqual(screen.getvalue(), "")

    def test_rows_never_exceed_console_width(self) -> None:
        screen = FakeTTY()
        with patch("progress._terminal_size", return_value=(72, 24)):
            with ConsoleProgress("U5", "inventory", stream=screen, refresh_interval=.01) as board:
                board.discovered(7)
                board.begin_cob("20261007", 7)
                board.set_file_total(9999)
                board.file_completed("inventoried", "ReportingStack/BreakFix/Housekeeping/very_long_job_name_that_would_wrap.log")
                board.message(
                    r"WARN: cannot stat \\ldnroot\data\IBCT\CVA\UAT\_U5\Logs\20261007\ReportingStack\BreakFix\very_long_file.log",
                    error=True,
                )
                time.sleep(.04)
        frames = screen.getvalue().split("\x1b[H\x1b[2J")
        visible = frames[-1].split("\x1b[?25h", 1)[0]
        self.assertTrue(visible)
        self.assertTrue(all(len(line) <= 70 for line in visible.splitlines()))

    def test_compaction_preserves_diagnostic_and_path_tail(self) -> None:
        event = r"WARN: cannot stat \\ldnroot\data\IBCT\CVA\UAT\_U5\Logs\20261007\ReportingStack\job.log"
        compact = _compact_event(event, 58)
        self.assertLessEqual(len(compact), 58)
        self.assertTrue(compact.startswith("WARN: cannot stat: ") or compact.startswith("... ") or "WARN" in compact)
        self.assertTrue(compact.endswith("job.log"))
        self.assertEqual(len(_fit("x" * 100, 20)), 20)

    def test_io_messages_do_not_fill_recent_events(self) -> None:
        board = ConsoleProgress("PROD", "inventory", stream=FakeTTY())
        board.message("I/O: metadata only; files listed 100", error=False)
        board.message("INVENTORY: report.csv", error=False)
        self.assertEqual(list(board.events), ["INVENTORY: report.csv"])


class AnalyzerProgressIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.root = self.folder / "Logs"
        self.output_dir = self.folder / "reports"
        self.config_path = self.folder / "config.json"
        self.config_path.write_text(json.dumps({"encoding": "utf-8-sig", "environments": {
            "PROD": {"logs_root": str(self.root)},
        }}), encoding="utf-8")
        for date in ("20261005", "20261006"):
            for index in range(5):
                path = self.root / date / "Downstream" / f"job{index}.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("2026-10-06 06:00:00 [1] INFO : Started\n", encoding="utf-8")

    def invoke(self, mode: str, *, terminal: bool = True, no_progress: bool = False) -> tuple[int, str, str]:
        screen: StringIO = FakeTTY() if terminal else StringIO()
        stderr = StringIO()
        args = ["--env", "PROD", "--config", str(self.config_path), "--mode", mode,
                "--output-dir", str(self.output_dir)]
        if no_progress:
            args.append("--no-progress")
        with redirect_stdout(screen), redirect_stderr(stderr):
            code = analyze.main(args)
        return code, screen.getvalue(), stderr.getvalue()

    def test_inventory_dashboard_counts_cobs_and_does_not_read_contents(self) -> None:
        with patch.object(analyze, "open_shared_log", side_effect=AssertionError("inventory read log")):
            status, text, errors = self.invoke("inventory")
        self.assertEqual(status, 0, errors)
        self.assertIn("\x1b[?1049h", text)
        self.assertIn("COB           : 20261006  (2/2)", text)
        self.assertIn("5 / 5", text)
        self.assertIn("Total handled : 10", text)
        self.assertIn("Mode: inventory; Processed: 10", text)
        self.assertIn("\x1b[?1049l", text)
        self.assertTrue((self.output_dir / "PROD" / "20261005" / "jobs.csv").exists())

    def test_enrich_dashboard_counts_parsed_and_cached(self) -> None:
        self.invoke("inventory", terminal=False)
        status, text, errors = self.invoke("enrich")
        self.assertEqual(status, 0, errors)
        self.assertIn("Enriched: 10", text)
        self.assertIn("Mode: enrich; Processed: 10", text)
        status, text, errors = self.invoke("enrich")
        self.assertEqual(status, 0, errors)
        self.assertIn("Cached        : 10", text)
        self.assertIn("Mode: enrich; Processed: 0", text)

    def test_redirected_output_uses_plain_text_without_progress(self) -> None:
        status, text, errors = self.invoke("inventory", terminal=False)
        self.assertEqual(status, 0, errors)
        self.assertNotIn("\x1b", text)
        self.assertIn("Mode: inventory; Processed: 10", text)

    def test_no_progress_forces_plain_output_in_terminal(self) -> None:
        status, text, errors = self.invoke("inventory", no_progress=True)
        self.assertEqual(status, 0, errors)
        self.assertNotIn("\x1b", text)
        self.assertIn("Mode: inventory; Processed: 10", text)

    def test_inventory_and_enrich_output_identical_with_progress_flag(self) -> None:
        self.invoke("inventory", terminal=True)
        original = (self.output_dir / "PROD" / "20261005" / "jobs.csv").read_bytes()
        # Metadata-only no-op should preserve CSV bytes.
        self.invoke("inventory", terminal=False)
        self.assertEqual(original, (self.output_dir / "PROD" / "20261005" / "jobs.csv").read_bytes())
        self.invoke("enrich", terminal=True)
        self.assertIn("Enriched", (self.output_dir / "PROD" / "20261005" / "jobs.csv").read_text(encoding="utf-8-sig"))

    def test_terminal_is_restored_on_keyboard_interrupt(self) -> None:
        with patch.object(analyze, "write_csv", side_effect=KeyboardInterrupt):
            status, text, errors = self.invoke("inventory")
        self.assertEqual(status, 130)
        self.assertTrue(text.endswith("\x1b[?25h\x1b[?1049l"))
        self.assertIn("CANCELLED", errors)

    def test_file_enumeration_occurs_once_per_cob(self) -> None:
        with patch.object(analyze, "iter_log_files", wraps=analyze.iter_log_files) as enumerator:
            status, _, err = self.invoke("inventory")
        self.assertEqual(status, 0, err)
        self.assertEqual(enumerator.call_count, 2)


if __name__ == "__main__":
    unittest.main()
