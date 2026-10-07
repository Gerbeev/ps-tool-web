#!/usr/bin/env python3
"""Optional LOCAL synthetic workload. Not an SMB or production benchmark."""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze


def run(root: Path, output: Path, now: datetime, mode: str) -> tuple[float, str]:
    stdout = StringIO()
    stderr = StringIO()
    start = time.perf_counter()
    analyze.write_csv(root=root, output_dir=output, environment="PROD", encoding="utf-8-sig",
                      only_date=None, delimiter=",", now=now, stdout=stdout, stderr=stderr,
                      mode=mode)
    return time.perf_counter() - start, stdout.getvalue() + "\n" + stderr.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="log-analyzer-benchmark-") as tmp:
        base = Path(tmp)
        logs = base / "Logs" / "20261005" / "Downstream"
        logs.mkdir(parents=True)
        line = b"2026-10-06 07:00:00 [1] INFO : Working\n"
        big = logs / "large_100mb.log"
        with big.open("wb") as handle:
            remaining = 100 * 1024 * 1024
            while remaining:
                block = (line * min(remaining // len(line), 8192)) or line[:remaining]
                handle.write(block)
                remaining -= len(block)
        for idx in range(2499):
            (logs / f"job_{idx:04d}.log").write_bytes(line)
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        output = base / "output"
        for label, mode in (("Initial inventory", "inventory"),
                            ("No-op inventory", "inventory"),
                            ("Initial enrichment", "enrich"),
                            ("No-op enrichment", "enrich")):
            elapsed, console = run(logs.parent.parent, output, now, mode)
            io_lines = [l for l in console.splitlines() if l.startswith("I/O:")]
            print(f"{label}: {elapsed:.2f}s; {io_lines[0] if io_lines else 'n/a'}")
            print("Errors:", console[-900:] if "SKIP:" in console else "none")
        with big.open("ab") as handle:
            handle.write(b"2026-10-07 07:01:00 [1] ERROR : End\n")
        elapsed, console = run(logs.parent.parent, output, now, "inventory")
        io_lines = [l for l in console.splitlines() if l.startswith("I/O:")]
        print(f"After append / inventory: {elapsed:.2f}s; {io_lines[0] if io_lines else 'n/a'}")
        elapsed, console = run(logs.parent.parent, output, now, "enrich")
        io_lines = [l for l in console.splitlines() if l.startswith("I/O:")]
        print(f"After append / enrichment: {elapsed:.2f}s; {io_lines[0] if io_lines else 'n/a'}")
        print("Errors:", console[-900:] if "SKIP:" in console else "none")


if __name__ == "__main__":
    main()
