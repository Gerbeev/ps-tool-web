#!/usr/bin/env python3
"""Standalone, streaming job-log analyzer. Python 3.11+, stdlib only."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, TextIO

TOOL_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG = TOOL_DIR / "config.local.json"
DEFAULT_CONFIG = LOCAL_CONFIG if LOCAL_CONFIG.is_file() else TOOL_DIR / "config.json"
DEFAULT_OUTPUT_DIR = TOOL_DIR / "output"

CSV_FIELDS = (
    "job_date",
    "job_name",
    "job_status",
    "start_time",
    "end_time",
    "duration",
    "restart_count",
    "warning_count",
    "error_count",
    "last_error",
)

# Observed log4net-style record: 2026-10-05 00:01:01,993 [1] INFO : message
# A line without a record prefix is a continuation, not a new event.
LOG_RECORD = re.compile(
    r"^\ufeff?\s*(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"(?:[,.]\d{1,6})?)\s+(?:\[[^\]\r\n]+\]\s+)?"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)"
    r"\s*:?\s*(?P<message>.*)$",
    re.IGNORECASE,
)
DATE_FOLDER = re.compile(r"^\d{8}$")


@dataclass(frozen=True)
class FileSummary:
    job_date: str
    job_name: str
    job_status: str
    start_time: str
    end_time: str
    duration: str
    restart_count: int
    warning_count: int
    error_count: int
    last_error: str


def parse_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace(",", "."))


def format_timestamp(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds") if value else ""


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def business_date_from_path(file_path: Path, root: Path) -> str | None:
    # Prefer the nearest YYYYMMDD folder relative to the configured Logs root.
    for folder in reversed(file_path.relative_to(root).parts[:-1]):
        if not DATE_FOLDER.fullmatch(folder):
            continue
        try:
            datetime.strptime(folder, "%Y%m%d")
        except ValueError:
            continue
        return folder
    return None


def iter_log_files(root: Path) -> Iterator[Path]:
    # Do not recurse into directory symlinks/junctions or read symlinked logs.
    for current, dirs, filenames in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink())
        for name in sorted(filenames):
            path = Path(current) / name
            if path.suffix.lower() == ".log" and path.is_file() and not path.is_symlink():
                yield path


def analyze_log(file_path: Path, job_date: str, encoding: str = "utf-8-sig") -> FileSummary:
    start: datetime | None = None
    finish: datetime | None = None
    first_info_message: str | None = None
    first_info_occurrences = 0
    warnings = 0
    errors = 0
    last_error = ""

    with file_path.open("r", encoding=encoding, errors="replace") as stream:
        for line in stream:
            # Remove line endings only; retain the entire original ERROR record.
            raw = line.rstrip("\r\n")
            record = LOG_RECORD.match(raw)
            if record:
                try:
                    timestamp = parse_timestamp(record.group("timestamp"))
                except ValueError:
                    timestamp = None
                if timestamp is not None:
                    if start is None:
                        start = timestamp
                    finish = timestamp

                level = record.group("level").upper()
                if level == "INFO" and first_info_message is None:
                    candidate = record.group("message").strip()
                    if candidate:
                        first_info_message = candidate
                if level in ("WARN", "WARNING"):
                    warnings += 1
                elif level == "ERROR":
                    errors += 1
                    last_error = raw

            # Count the exact initial INFO message wherever it reoccurs in the
            # physical log, including the first occurrence. Extra occurrences
            # represent subsequent starts, not the first start.
            if first_info_message:
                first_info_occurrences += raw.count(first_info_message)

    duration = ""
    if start is not None and finish is not None and finish >= start:
        duration = format_duration(int((finish - start).total_seconds()))

    return FileSummary(
        job_date=job_date,
        job_name=file_path.stem,
        job_status="Completed",
        start_time=format_timestamp(start),
        end_time=format_timestamp(finish),
        duration=duration,
        restart_count=max(0, first_info_occurrences - 1),
        warning_count=warnings,
        error_count=errors,
        last_error=last_error,
    )


def excel_safe(text: str) -> str:
    # Protect users opening a CSV in Excel from formula injection via filenames
    # or log messages. Ordinary source strings are unchanged.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def resolve_root(config_path: Path, environment: str) -> tuple[Path, str]:
    with config_path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict) or not isinstance(config.get("environments"), dict):
        raise ValueError("Configuration requires an 'environments' object")
    environments = config["environments"]
    if environment not in environments:
        names = ", ".join(sorted(environments))
        raise ValueError(f"Unknown environment {environment!r}; configured: {names}")
    entry = environments[environment]
    if not isinstance(entry, dict) or not isinstance(entry.get("logs_root"), str):
        raise ValueError(f"Missing logs_root for environment {environment}")
    location = entry["logs_root"].strip()
    if not location:
        raise ValueError(f"logs_root is not configured for {environment}; edit {config_path}")
    encoding = config.get("encoding", "utf-8-sig")
    if not isinstance(encoding, str) or not encoding:
        raise ValueError("encoding must be a non-empty Python codec name")
    root = Path(os.path.expandvars(os.path.expanduser(location)))
    if not root.is_absolute():
        root = config_path.resolve().parent / root
    return root, encoding


def write_csv(
    *, root: Path, output: Path, encoding: str, only_date: str | None,
    delimiter: str, stdout: TextIO | None = None, stderr: TextIO | None = None,
) -> tuple[int, int, int, int]:
    """Produce CSV atomically. Returns (processed, skipped, warn_count, error_count)."""
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    if not root.is_dir():
        raise ValueError(f"Logs directory does not exist or cannot be accessed: {root}")
    if len(delimiter) != 1:
        raise ValueError("CSV delimiter must be one character")

    output.parent.mkdir(parents=True, exist_ok=True)
    processed = skipped = warnings = errors = 0
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=output.parent,
            prefix=".log-analyzer-", suffix=".tmp", delete=False,
        ) as stream:
            tmp_path = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, delimiter=delimiter)
            writer.writeheader()
            for log_path in iter_log_files(root):
                date = business_date_from_path(log_path, root)
                if date is None:
                    skipped += 1
                    print(f"SKIP: no valid YYYYMMDD parent folder: {log_path}", file=stderr)
                    continue
                if only_date and only_date != date:
                    continue
                try:
                    result = analyze_log(log_path, date, encoding=encoding)
                except OSError as exc:
                    skipped += 1
                    print(f"SKIP: cannot read {log_path}: {exc}", file=stderr)
                    continue
                row = vars(result).copy()
                row["job_name"] = excel_safe(result.job_name)
                row["last_error"] = excel_safe(result.last_error)
                writer.writerow(row)
                processed += 1
                warnings += result.warning_count
                errors += result.error_count
                if not result.start_time or not result.end_time:
                    print(f"WARN: no parseable timestamps in: {log_path}", file=stderr)
                elif not result.duration:
                    print(f"WARN: last timestamp precedes first: {log_path}", file=stderr)

        if processed == 0:
            raise ValueError("No logs with a valid business-date folder found; CSV not replaced")
        os.replace(tmp_path, output)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    print(f"CSV: {output}", file=stdout)
    print(f"Processed: {processed}; skipped: {skipped}; WARN: {warnings}; ERROR: {errors}", file=stdout)
    return processed, skipped, warnings, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze scheduler log files recursively to CSV")
    parser.add_argument("--env", required=True, help="Environment in config.json, e.g. PROD or U5")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="JSON configuration file")
    parser.add_argument("--output", type=Path, help="Output CSV path (default: tools/log_analyzer/output/<ENV>_jobs.csv)")
    parser.add_argument("--date", help="Optional date-folder filter, YYYYMMDD (default: all dates)")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter, comma (default) or semicolon")
    args = parser.parse_args(argv)

    environment = args.env.strip().upper()
    if args.date:
        if not DATE_FOLDER.fullmatch(args.date):
            parser.error("--date must be YYYYMMDD")
        try:
            datetime.strptime(args.date, "%Y%m%d")
        except ValueError:
            parser.error("--date is not a valid calendar date")

    try:
        root, encoding = resolve_root(args.config, environment)
        output = args.output or (DEFAULT_OUTPUT_DIR / f"{environment}_jobs.csv")
        _, skipped, _, _ = write_csv(
            root=root, output=output, encoding=encoding,
            only_date=args.date, delimiter=args.delimiter,
        )
        return 2 if skipped else 0
    except (ValueError, OSError, UnicodeError, LookupError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
