"""Root-level COB selection and scan-window regressions."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze


class CobSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.root = self.work / "Logs"
        self.root.mkdir()
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

    def make_cob(self, date: str, *, log: bool = False) -> Path:
        folder = self.root / date
        folder.mkdir(parents=True, exist_ok=True)
        if log:
            system = folder / "Downstream"
            system.mkdir(exist_ok=True)
            (system / f"job_{date}.log").write_text(
                f"{date[:4]}-{date[4:6]}-{date[6:]} 10:00:00 [1] INFO : Start\n",
                encoding="utf-8",
            )
        return folder

    def test_only_latest_root_level_cobs_are_selected(self) -> None:
        start = self.now.date() - timedelta(days=19)
        for offset in range(20):
            self.make_cob((start + timedelta(days=offset)).strftime("%Y%m%d"))

        # Must never be traversed even though it contains a duplicate-looking COB.
        (self.root / "Archive" / "20261007" / "Nested").mkdir(parents=True)
        (self.root / "tmp").mkdir()
        self.make_cob("20261008")  # Future date: ignored.

        selected = analyze.discover_cobs(self.root, now=self.now, limit=7)
        self.assertEqual(
            [date for date, _ in selected],
            ["20261001", "20261002", "20261003", "20261004", "20261005", "20261006", "20261007"],
        )

    def test_scan_limit_prevents_old_cobs_from_being_processed(self) -> None:
        for date in ("20261001", "20261002", "20261003", "20261004"):
            self.make_cob(date, log=True)
        (self.root / "Archive" / "20261004" / "Downstream").mkdir(parents=True)
        (self.root / "Archive" / "20261004" / "Downstream" / "duplicate.log").write_text("x\n")

        output = self.work / "out"
        result = analyze.write_csv(
            root=self.root, output_dir=output, environment="PROD",
            encoding="utf-8", only_date=None, delimiter=",", mode="inventory",
            now=self.now, policy=analyze.IncrementalPolicy(cob_scan_limit=2),
            stdout=StringIO(), stderr=StringIO(),
        )
        self.assertEqual(result[0], 2)
        self.assertFalse((output / "PROD" / "20261001").exists())
        self.assertFalse((output / "PROD" / "20261002").exists())
        self.assertTrue((output / "PROD" / "20261003" / "jobs.csv").is_file())
        self.assertTrue((output / "PROD" / "20261004" / "jobs.csv").is_file())

    def test_explicit_date_can_select_older_root_cob(self) -> None:
        for date in ("20261001", "20261006", "20261007"):
            self.make_cob(date)
        selected = analyze.discover_cobs(
            self.root, now=self.now, limit=1, only_date="20261001",
        )
        self.assertEqual([date for date, _ in selected], ["20261001"])

    def test_scan_limit_config_is_validated(self) -> None:
        policy = analyze.policy_from_config({"incremental": {"cob_scan_limit": 9}})
        self.assertEqual(policy.cob_scan_limit, 9)
        for value in (0, True, 10001):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "cob_scan_limit"):
                analyze.policy_from_config({"incremental": {"cob_scan_limit": value}})


if __name__ == "__main__":
    unittest.main()
