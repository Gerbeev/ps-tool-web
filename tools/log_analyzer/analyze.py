#!/usr/bin/env python3
"""Standalone, streaming job-log analyzer. Python 3.11+, stdlib only."""

from __future__ import annotations

import argparse
import codecs
from collections import deque
from concurrent.futures import ThreadPoolExecutor, Future
import hashlib
from contextlib import contextmanager
import io
import csv
import json
import os
import re
import sys
import stat as statmod
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, NamedTuple, TextIO

from progress import ConsoleProgress

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = TOOL_DIR / "config.json"
DEFAULT_OUTPUT_DIR = TOOL_DIR / "output"

CSV_FIELDS = (
    "job_date",
    "system",
    "job_name",
    "job_status",
    "last_modified_time",
    "start_time",
    "end_time",
    "duration",
    "restart_count",
    "warning_count",
    "error_count",
    "last_error",
    "file_size_bytes",
    "enrichment_status",
    "enriched_at_utc",
    "activity_status",
    "path",
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
ENV_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")
ALLOWED_ENVIRONMENTS = ("PROD", "U5", "U1", "U6")


@dataclass(frozen=True)
class FileSummary:
    job_date: str
    system: str
    job_name: str
    job_status: str
    activity_status: str
    last_modified_time: str
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


def source_metadata_from_path(file_path: Path, root: Path) -> tuple[str | None, str]:
    """Extract COB and system from Logs/YYYYMMDD/<system>/.../job.log.

    The immediate directory after the nearest valid COB folder is the system.
    Files directly under a COB folder have no identifiable system.
    """
    folders = file_path.relative_to(root).parts[:-1]
    for index in range(len(folders) - 1, -1, -1):
        folder = folders[index]
        if not DATE_FOLDER.fullmatch(folder):
            continue
        try:
            datetime.strptime(folder, "%Y%m%d")
        except ValueError:
            continue
        return folder, folders[index + 1] if index + 1 < len(folders) else ""
    return None, ""


def business_date_from_path(file_path: Path, root: Path) -> str | None:
    return source_metadata_from_path(file_path, root)[0]


def iter_log_files(root: Path) -> Iterator[tuple[Path, os.stat_result]]:
    """Use scandir metadata once per log, avoiding redundant SMB stat calls.

    Fail closed on any directory listing error. Never follow junctions/symlinks.
    """
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name.lower())
        dirs: list[Path] = []
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append(Path(entry.path))
            elif entry.name.lower().endswith(".log"):
                metadata = entry.stat(follow_symlinks=False)
                if statmod.S_ISREG(metadata.st_mode):
                    yield Path(entry.path), metadata
        stack.extend(reversed(dirs))


# The analyzer never requests source write/delete access or byte-range locks.
# Win32 sharing flags permit a scheduler to continue appending while we read.
@lru_cache(maxsize=1)
def _windows_file_api():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                            wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    return create_file, close_handle


@contextmanager
def open_shared_log(file_path: Path) -> Iterator[io.BufferedReader]:
    if os.name != "nt":
        with file_path.open("rb") as stream:
            yield stream
        return

    # The standard Python open() does not expose explicit Win32 share flags.
    import ctypes
    import msvcrt
    create_file, close_handle = _windows_file_api()

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ_WRITE_DELETE = 0x00000001 | 0x00000002 | 0x00000004
    OPEN_EXISTING = 3
    FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    handle = create_file(str(file_path), GENERIC_READ, FILE_SHARE_READ_WRITE_DELETE,
                         None, OPEN_EXISTING,
                         FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        raise OSError(code, ctypes.FormatError(code), str(file_path))
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    except BaseException:
        close_handle(handle)
        raise
    with os.fdopen(fd, "rb") as stream:
        yield stream


# Keep parser checkpoints as plain JSON so upgrading the tool does not need a DB.
# Offset is the last *fully terminated* line. A partial tail will be replayed,
# which is essential when the writer is currently appending.
MAX_LINE_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 256 * 1024
ANCHOR_TAIL_BYTES = 64 * 1024
ANCHOR_HEAD_BYTES = 4 * 1024


def _new_accumulator() -> dict:
    return {"start": "", "finish": "", "first_info": "", "occurrences": 0,
            "warnings": 0, "errors": 0, "last_error": "", "offset": 0}


def _record(raw: str, data: dict) -> None:
    match = LOG_RECORD.match(raw)
    if match:
        try:
            stamp = format_timestamp(parse_timestamp(match.group("timestamp")))
        except ValueError:
            stamp = ""
        if stamp:
            if not data["start"]:
                data["start"] = stamp
            data["finish"] = stamp
        level = match.group("level").upper()
        if level == "INFO" and not data["first_info"]:
            candidate = match.group("message").strip()
            if candidate:
                data["first_info"] = candidate
        if level in ("WARN", "WARNING"):
            data["warnings"] += 1
        elif level == "ERROR":
            data["errors"] += 1
            data["last_error"] = raw
    if data["first_info"]:
        data["occurrences"] += raw.count(data["first_info"])


def _summary(data: dict, file_path: Path, job_date: str, system: str) -> FileSummary:
    duration = ""
    if data["start"] and data["finish"]:
        start = datetime.fromisoformat(data["start"])
        finish = datetime.fromisoformat(data["finish"])
        if finish >= start:
            duration = format_duration(int((finish - start).total_seconds()))
    return FileSummary(
        job_date=job_date, system=system, job_name=file_path.stem,
        job_status="Completed", activity_status="Unknown", last_modified_time="",
        start_time=data["start"], end_time=data["finish"], duration=duration,
        restart_count=max(0, data["occurrences"] - 1),
        warning_count=data["warnings"], error_count=data["errors"],
        last_error=data["last_error"],
    )


def _line_codec(stream: io.BufferedReader, encoding: str) -> tuple[str, bytes, int]:
    name = codecs.lookup(encoding).name
    if name == "utf-16":
        location = stream.tell()
        stream.seek(0)
        bom = stream.read(2)
        stream.seek(location)
        if bom == b"\xff\xfe":
            name = "utf-16-le"
        elif bom == b"\xfe\xff":
            name = "utf-16-be"
        else:
            raise UnicodeError("UTF-16 file lacks a byte-order mark")
    if name == "utf-32":
        location = stream.tell()
        stream.seek(0)
        bom = stream.read(4)
        stream.seek(location)
        if bom == b"\xff\xfe\x00\x00":
            name = "utf-32-le"
        elif bom == b"\x00\x00\xfe\xff":
            name = "utf-32-be"
        else:
            raise UnicodeError("UTF-32 file lacks a byte-order mark")
    if name == "utf-32-le":
        return name, b"\n\x00\x00\x00", 4
    if name == "utf-32-be":
        return name, b"\x00\x00\x00\n", 4
    if name == "utf-16-le":
        return name, b"\n\x00", 2
    if name == "utf-16-be":
        return name, b"\x00\n", 2
    # Python's other encodings must use byte-compatible LF (UTF-8, cp1252...).
    if name == "utf-7":
        raise UnicodeError(f"unsupported checkpoint encoding: {encoding}")
    return name, b"\n", 1


def _snapshot_lines(stream: io.BufferedReader, *, offset: int, limit: int,
                    separator: bytes, alignment: int) -> Iterator[tuple[bytes, int, bool]]:
    """Emit snapshot lines with a fast path and bounded, linear long-line growth.

    Short lines retain the bytes-based path; a large unterminated line switches
    to an in-place bytearray and searches only its newly appended suffix.
    Multi-byte newline separators may straddle a read-chunk boundary.
    """
    stream.seek(offset)
    left = limit - offset
    pending: bytes | bytearray = b""
    pending_offset = offset
    while left:
        chunk = stream.read(min(READ_CHUNK_BYTES, left))
        if not chunk:
            raise OSError("source log was truncated during snapshot reading")
        left -= len(chunk)

        if len(pending) <= READ_CHUNK_BYTES:
            buffer = bytes(pending) + chunk
            cursor = 0
            while True:
                index = buffer.find(separator, cursor)
                while index >= 0 and (pending_offset + index) % alignment:
                    index = buffer.find(separator, index + 1)
                if index < 0:
                    break
                end = index + len(separator)
                yield buffer[cursor:end], pending_offset + end, True
                cursor = end
            pending = buffer[cursor:]
            pending_offset += cursor
        else:
            if not isinstance(pending, bytearray):
                pending = bytearray(pending)
            search_at = max(0, len(pending) - len(separator) + 1)
            pending.extend(chunk)
            cursor = 0
            while True:
                index = pending.find(separator, max(search_at, cursor))
                while index >= 0 and (pending_offset + index) % alignment:
                    index = pending.find(separator, index + 1)
                if index < 0:
                    break
                end = index + len(separator)
                if end - cursor > MAX_LINE_BYTES:
                    raise OSError("log line exceeds safe 16 MiB limit")
                yield bytes(pending[cursor:end]), pending_offset + end, True
                cursor = end
                search_at = cursor
            if cursor:
                del pending[:cursor]
                pending_offset += cursor
        if len(pending) > MAX_LINE_BYTES:
            raise OSError("unterminated log line exceeds safe 16 MiB limit")
    if pending:
        yield bytes(pending), limit, False


def _scan_from(stream: io.BufferedReader, *, start_offset: int, limit: int,
               encoding: str, initial: dict, include_tail: bool,
               file_path: Path, job_date: str, system: str) -> tuple[FileSummary, dict, bool]:
    codec, separator, alignment = _line_codec(stream, encoding)
    committed = initial.copy()
    if start_offset % alignment:
        raise ValueError("checkpoint offset is not aligned with log encoding")
    tail: str | None = None
    for line, end, terminated in _snapshot_lines(stream, offset=start_offset, limit=limit,
                                                   separator=separator, alignment=alignment):
        raw = line.decode(codec, errors="replace").rstrip("\r\n")
        if terminated:
            _record(raw, committed)
            committed["offset"] = end
        else:
            tail = raw
    display = committed.copy()
    tail_included = tail is not None and include_tail
    if tail_included:
        _record(tail, display)
    return _summary(display, file_path, job_date, system), committed, tail_included


def _analyze_stream(
    stream: io.BufferedReader, file_path: Path, job_date: str,
    encoding: str, system: str, byte_limit: int | None,
    ignore_incomplete_tail: bool, *, checkpoint: dict | None = None,
) -> FileSummary:
    limit = byte_limit if byte_limit is not None else os.fstat(stream.fileno()).st_size
    summary, state, included = _scan_from(
        stream, start_offset=0, limit=limit, encoding=encoding,
        initial=_new_accumulator(), include_tail=not ignore_incomplete_tail,
        file_path=file_path, job_date=job_date, system=system,
    )
    if checkpoint is not None:
        checkpoint.update(state)
        checkpoint["tail_included"] = included
    return summary


def _prefix_anchor(stream: io.BufferedReader, offset: int) -> str:
    """Quick rewrite/rotation guard: first 4 KiB and last 64 KiB of parsed prefix."""
    original = stream.tell()
    try:
        stream.seek(0)
        head = stream.read(min(ANCHOR_HEAD_BYTES, offset))
        stream.seek(max(0, offset - ANCHOR_TAIL_BYTES))
        tail = stream.read(min(ANCHOR_TAIL_BYTES, offset))
        if len(head) != min(ANCHOR_HEAD_BYTES, offset) or len(tail) != min(ANCHOR_TAIL_BYTES, offset):
            raise OSError("source truncated while reading prefix anchor")
        return hashlib.sha256(head + tail).hexdigest()
    finally:
        stream.seek(original)


@dataclass(frozen=True)
class ParseOutcome:
    summary: FileSummary
    signature: list[int]
    checkpoint: dict
    anchor: str
    bytes_read: int
    mode: str
    identity: list[int]


def _snapshot_stable(path: Path, stream: io.BufferedReader,
                     initial: os.stat_result) -> bool:
    last = os.fstat(stream.fileno())
    current = path.stat()
    if last.st_size < initial.st_size or current.st_size < initial.st_size:
        return False
    for stat in (last, current):
        if stat.st_size == initial.st_size and stat.st_mtime_ns != initial.st_mtime_ns:
            return False
        if initial.st_ino and stat.st_ino and (initial.st_dev, initial.st_ino) != (stat.st_dev, stat.st_ino):
            return False
    return True


def analyze_log(
    file_path: Path, job_date: str, encoding: str = "utf-8-sig", *, system: str = "",
) -> FileSummary:
    """Direct one-pass parse. Concurrent-safe snapshots are used by stable_summary."""
    with open_shared_log(file_path) as stream:
        return _analyze_stream(stream, file_path, job_date, encoding, system, None, False)


def excel_safe(text: str) -> str:
    # Protect users opening a CSV in Excel from formula injection via filenames
    # or log messages. Ordinary source strings are unchanged.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def validate_config(config: object) -> dict:
    """Validate once for the CLI and menu; discard unsupported environments."""
    if not isinstance(config, dict) or not isinstance(config.get("environments"), dict):
        raise ValueError("Configuration requires an 'environments' object")
    entries = config["environments"]
    normalized: dict = {}
    for name in ALLOWED_ENVIRONMENTS:
        if name not in entries:
            continue
        configured = entries[name]
        if not isinstance(configured, dict) or not isinstance(configured.get("logs_root"), str):
            raise ValueError(f"Environment {name} requires a string logs_root")
        normalized[name] = configured
    encoding = config.get("encoding", "utf-8-sig")
    if not isinstance(encoding, str) or not encoding.strip():
        raise ValueError("encoding must be a non-empty Python codec name")
    if codecs.lookup(encoding).name == "utf-7":
        raise ValueError("UTF-7 is unsupported for incremental line checkpoints")
    policy_from_config(config)
    return {**config, "environments": normalized}


def load_config(config_path: Path) -> dict:
    """Read and validate one explicit config (config.local.json is ignored)."""
    with config_path.open("r", encoding="utf-8") as stream:
        return validate_config(json.load(stream))


def resolve_root(config_path: Path, environment: str, *, config: dict | None = None) -> tuple[Path, str]:
    if environment not in ALLOWED_ENVIRONMENTS:
        raise ValueError(f"Unsupported environment {environment!r}; allowed: {', '.join(ALLOWED_ENVIRONMENTS)}")
    config = config if config is not None else load_config(config_path)
    environments = config["environments"]
    if environment not in environments:
        raise ValueError(f"Environment {environment!r} is missing from {config_path}")
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


# Bump when CSV extraction semantics or the on-disk state shape change.
STATE_VERSION = 1
DEFAULT_MIN_ACTIVE_DAYS = 7
DEFAULT_QUIET_HOURS = 72
DEFAULT_RECENT_MINUTES = 5
DEFAULT_READ_WORKERS = 4
DEFAULT_COB_SCAN_LIMIT = 7


@dataclass(frozen=True)
class IncrementalPolicy:
    min_active_days: int = DEFAULT_MIN_ACTIVE_DAYS
    quiet_hours: int = DEFAULT_QUIET_HOURS
    recent_minutes: int = DEFAULT_RECENT_MINUTES
    read_workers: int = DEFAULT_READ_WORKERS
    cob_scan_limit: int = DEFAULT_COB_SCAN_LIMIT


def policy_from_config(config: dict) -> IncrementalPolicy:
    options = config.get("incremental", {})
    if not isinstance(options, dict):
        raise ValueError("incremental must be a JSON object")
    days = options.get("min_active_days", DEFAULT_MIN_ACTIVE_DAYS)
    hours = options.get("quiet_hours", DEFAULT_QUIET_HOURS)
    recent_minutes = options.get("recent_minutes", DEFAULT_RECENT_MINUTES)
    workers = options.get("read_workers", DEFAULT_READ_WORKERS)
    cob_scan_limit = options.get("cob_scan_limit", DEFAULT_COB_SCAN_LIMIT)
    for name, value in (("min_active_days", days), ("quiet_hours", hours), ("recent_minutes", recent_minutes)):
        if type(value) is not int or value < 1 or value > 87600:
            raise ValueError(f"incremental.{name} must be an integer between 1 and 87600")
    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("incremental.read_workers must be an integer from 1 to 16")
    if type(cob_scan_limit) is not int or not 1 <= cob_scan_limit <= 10000:
        raise ValueError("incremental.cob_scan_limit must be an integer from 1 to 10000")
    return IncrementalPolicy(days, hours, recent_minutes, workers, cob_scan_limit)


def read_policy(config_path: Path) -> IncrementalPolicy:
    # Also supports policy-only JSON files used by embedders and tests.
    with config_path.open("r", encoding="utf-8") as stream:
        return policy_from_config(json.load(stream))


def valid_cob(value: str) -> bool:
    if not DATE_FOLDER.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def discover_cobs(
    root: Path, *, now: datetime, limit: int, only_date: str | None = None,
) -> list[tuple[str, Path]]:
    """Return eligible COB folders directly beneath ``root``.

    Only root-level directories with a valid YYYYMMDD name are candidates.
    Non-COB directories are ignored without recursion. Future COB dates are
    ignored. Normal scans take only the newest ``limit`` existing folders; an
    explicit ``only_date`` selects that root-level COB regardless of the limit.
    """
    today = now.strftime("%Y%m%d")
    candidates: list[tuple[str, Path]] = []
    with os.scandir(root) as iterator:
        for entry in iterator:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            name = entry.name
            if not valid_cob(name) or name > today:
                continue
            if only_date is not None and name != only_date:
                continue
            candidates.append((name, Path(entry.path)))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if only_date is not None:
        return candidates
    # Select newest N first, then process oldest-to-newest for stable output/progress.
    return list(reversed(candidates[:limit]))


class CobResult(NamedTuple):
    parsed: int = 0
    cached: int = 0
    skipped: int = 0
    warnings: int = 0
    errors: int = 0
    written: int = 0
    closed: int = 0
    removed: int = 0


@dataclass(frozen=True)
class CobLog:
    path: Path
    stat: os.stat_result
    key: str
    system: str


def iter_cob_logs(
    folder: Path, stderr: TextIO, progress: ConsoleProgress | None,
) -> Iterator[CobLog | None]:
    """Enumerate each COB once; None represents a skipped nested COB log."""
    entries = list(iter_log_files(folder)) if progress is not None else iter_log_files(folder)
    if progress is not None:
        progress.set_file_total(len(entries))
    for path, stat in entries:
        relative = path.relative_to(folder)
        if any(valid_cob(part) for part in relative.parts[:-1]):
            print(f"SKIP: nested COB directory not supported: {path}", file=stderr)
            if progress is not None:
                progress.file_completed("skipped", relative.as_posix())
            yield None
        else:
            yield CobLog(path, stat, relative.as_posix(),
                         relative.parts[0] if len(relative.parts) > 1 else "")


def file_signature(stat: os.stat_result) -> list[int]:
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def source_fingerprint(root: Path, encoding: str, delimiter: str) -> str:
    info = json.dumps([os.path.normcase(str(root.resolve())), encoding, delimiter, STATE_VERSION])
    return hashlib.sha256(info.encode("utf-8")).hexdigest()


def load_state(path: Path, date: str, fingerprint: str, stderr: TextIO) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or data.get("version") != STATE_VERSION or data.get("cob") != date or data.get("source_id") != fingerprint:
            print(f"INFO: invalidated state for COB {date} (configuration or schema changed)", file=stderr)
            return None
        if data.get("status") not in ("open", "closed"):
            raise ValueError("invalid status")
        if data["status"] == "open":
            files = data.get("files")
            if not isinstance(files, dict):
                raise ValueError("files object missing")
            for key, entry in files.items():
                if (not isinstance(key, str) or not isinstance(entry, dict)
                        or not isinstance(entry.get("row"), dict)
                        or not isinstance(entry.get("signature"), list)
                        or len(entry["signature"]) != 3
                        or any(type(value) is not int or value < 0 for value in entry["signature"])):
                    raise ValueError("invalid file entry in cached state")
        return data
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"WARN: ignoring unreadable state {path}: {exc}", file=stderr)
        return None


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=".state-", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def csv_schema_matches(path: Path, delimiter: str) -> bool:
    """Return True when an existing report already uses the current CSV schema."""
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream, delimiter=delimiter), [])
    except (OSError, UnicodeError, csv.Error):
        return False
    return tuple(header) == CSV_FIELDS


def atomic_csv(path: Path, files: dict, delimiter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
            prefix=".log-analyzer-", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, delimiter=delimiter)
            writer.writeheader()
            for rel_path in sorted(files):
                cached = files[rel_path]["row"]
                # Backward compatibility: manifests created before the column rename
                # may still store the same value under ``relative_path``.
                if "path" not in cached and "relative_path" in cached:
                    cached = {**cached, "path": cached.get("relative_path", "")}
                # Older manifests may omit newer columns; never let arbitrary
                # extension fields leak into CSV or abort an atomic refresh.
                row = {field: cached.get(field, "") for field in CSV_FIELDS}
                for field in ("system", "job_name", "last_error", "path"):
                    value = row[field]
                    row[field] = excel_safe(str(value)) if value is not None else ""
                writer.writerow(row)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@contextmanager
def environment_lock(environment_dir: Path) -> Iterator[None]:
    """Prevent two independent runs from corrupting the same env's state/reports."""
    environment_dir.mkdir(parents=True, exist_ok=True)
    lock = environment_dir / ".analyzer.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"Analyzer is already running, or a stale lock exists: {lock}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()}\nstarted={datetime.now(timezone.utc).isoformat()}\n")
        yield
    finally:
        lock.unlink(missing_ok=True)


def activity_fields(mtime_ns: int, now: datetime, recent_minutes: int) -> dict[str, str]:
    elapsed = now.timestamp() - mtime_ns / 1_000_000_000
    if elapsed < -60:
        activity = "ClockSkew"
    elif elapsed <= recent_minutes * 60:
        activity = "RecentlyModified"
    else:
        activity = "NotRecentlyModified"
    modified = datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=timezone.utc)
    return {"activity_status": activity, "last_modified_time": modified.isoformat(timespec="milliseconds")}


def inventory_row(log_path: Path, cob: str, system: str, key: str,
                  signature: list[int], now: datetime, policy: IncrementalPolicy) -> dict:
    """Metadata-only CSV row. Empty metrics mean unknown, not zero."""
    return {
        "job_date": cob, "system": system, "job_name": log_path.stem,
        "job_status": "Unknown",
        **activity_fields(signature[1], now, policy.recent_minutes),
        "start_time": "", "end_time": "", "duration": "",
        "restart_count": "", "warning_count": "", "error_count": "", "last_error": "",
        "path": key, "file_size_bytes": signature[0],
        "enrichment_status": "Pending", "enriched_at_utc": "",
    }


def enrich_status(row: dict) -> str:
    """Existing manifests from previous releases contain fully parsed rows."""
    return row.get("enrichment_status", "Enriched")


def inventory_cob(
    *, cob: str, folder: Path, env_dir: Path, fingerprint: str, delimiter: str,
    policy: IncrementalPolicy, now: datetime, force: bool,
    stdout: TextIO, stderr: TextIO,
    progress: ConsoleProgress | None = None,
) -> CobResult:
    """List only names and stat metadata. NEVER opens log file contents."""
    report = env_dir / cob / "jobs.csv"
    state_path = env_dir / ".state" / f"{cob}.json"
    state = load_state(state_path, cob, fingerprint, stderr)
    if state is not None and state["status"] == "closed" and report.is_file() and not force:
        return CobResult(0, 0, 0, 0, 0, 0, 1, 0)
    previous = state.get("files", {}) if state is not None and not force else {}
    files: dict[str, dict] = {}
    changed_rows = 0
    cached = skipped = 0
    for log in iter_cob_logs(folder, stderr, progress):
        if log is None:
            skipped += 1
            continue
        log_path, stat, key, system = log.path, log.stat, log.key, log.system
        signature = file_signature(stat)
        old = previous.get(key)
        base = inventory_row(log_path, cob, system, key, signature, now, policy)
        if isinstance(old, dict) and isinstance(old.get("row"), dict):
            prev_row = old["row"]
            if "path" not in prev_row and "relative_path" in prev_row:
                prev_row = {**prev_row, "path": prev_row.get("relative_path", "")}
            prev_row.pop("relative_path", None)
            parsed_sig = old.get("parsed_signature")
            if parsed_sig is None and enrich_status(prev_row) == "Enriched":
                parsed_sig = old.get("signature")
            if old.get("signature") == signature:
                row = {**base, **prev_row, **activity_fields(signature[1], now, policy.recent_minutes),
                       "path": key, "file_size_bytes": signature[0],
                       "enrichment_status": enrich_status(prev_row)}
                cached += 1
            else:
                row = base
                row["enrichment_status"] = ("Stale" if parsed_sig is not None else "Pending")
                changed_rows += 1
            entry = {**old, "signature": signature, "row": row}
            if parsed_sig is not None:
                entry["parsed_signature"] = parsed_sig
        else:
            entry = {"signature": signature, "row": base}
            changed_rows += 1
        if entry["row"] != (old.get("row") if isinstance(old, dict) else None):
            changed_rows += int(old is not None and old.get("signature") == signature)
        files[key] = entry
        if progress is not None:
            progress.file_completed("cached" if old is not None and old.get("signature") == signature
                                    else "inventoried", key)

    if not files:
        if state is not None and report.is_file():
            print(f"WARN: no source logs for {cob}; previous report preserved", file=stderr)
            return CobResult(0, 0, 1, 0, 0, 0, 0, 0)
        return CobResult(0, 0, skipped, 0, 0, 0, 0, 0)

    removed = len(set(previous) - set(files))
    changed = (force or state is None or changed_rows > 0 or removed > 0
               or not csv_schema_matches(report, delimiter))
    if changed:
        atomic_csv(report, files, delimiter)
        print(f"INVENTORY: {report} ({len(files)} files; new/changed {changed_rows}, cached {cached})", file=stdout)

    # Inventory must NEVER finalize a COB: un-enriched logs still need processing.
    new_state = {
        "version": STATE_VERSION, "cob": cob, "source_id": fingerprint,
        "status": "open", "job_count": len(files),
        "last_updated_utc": now.astimezone(timezone.utc).isoformat(),
        "files": files,
    }
    if changed or state is None:
        atomic_json(state_path, new_state)
    print(f"I/O: metadata only; opened log contents 0; files listed {len(files)}", file=stdout)
    warnings = sum(int(item["row"].get("warning_count") or 0) for item in files.values())
    errors = sum(int(item["row"].get("error_count") or 0) for item in files.values())
    # First value is the number of metadata rows updated, not parsed log files.
    return CobResult(changed_rows, cached, skipped, warnings, errors, int(changed), 0, removed)


def stable_summary(
    log_path: Path, date: str, system: str, encoding: str, *,
    now: datetime | None = None, recent_minutes: int = DEFAULT_RECENT_MINUTES,
) -> ParseOutcome | None:
    """Full bounded scan, allowing writers to append. Never retries a hot log."""
    with open_shared_log(log_path) as stream:
        initial = os.fstat(stream.fileno())
        scan_time = now if now is not None else datetime.now(timezone.utc)
        recent = scan_time.timestamp() - initial.st_mtime_ns / 1e9 <= recent_minutes * 60
        state: dict = {}
        summary = _analyze_stream(stream, log_path, date, encoding, system,
                                  initial.st_size, recent, checkpoint=state)
        anchor = _prefix_anchor(stream, state["offset"])
        if not _snapshot_stable(log_path, stream, initial):
            return None
    return ParseOutcome(summary, file_signature(initial), state, anchor, initial.st_size, "full",
                        [initial.st_dev, initial.st_ino])


def appended_summary(
    log_path: Path, date: str, system: str, encoding: str, old: dict, *,
    now: datetime, recent_minutes: int,
) -> ParseOutcome | None:
    """Read only the suffix after the last *complete* cached line.

    If the file was replaced, rewritten, or truncated, caller will reparse it
    from byte zero. This is a best-effort guard against in-place middle rewrites;
    unlike a full hash it costs at most 68 KiB of reads per changed file.
    """
    saved = old.get("checkpoint")
    if not isinstance(saved, dict) or any(key not in saved for key in _new_accumulator()):
        return None
    if not isinstance(old.get("anchor"), str):
        return None
    offset = saved["offset"]
    previous = old.get("signature")
    if not isinstance(offset, int) or offset < 0 or not isinstance(previous, list) or len(previous) < 2:
        return None
    with open_shared_log(log_path) as stream:
        initial = os.fstat(stream.fileno())
        if initial.st_size < previous[0] or offset > initial.st_size:
            return None
        if initial.st_size == previous[0] and initial.st_mtime_ns != previous[1]:
            return None
        identity = old.get("identity")
        if (isinstance(identity, list) and len(identity) == 2 and identity[1] and initial.st_ino and
                identity != [initial.st_dev, initial.st_ino]):
            return None
        if _prefix_anchor(stream, offset) != old["anchor"]:
            return None
        recent = now.timestamp() - initial.st_mtime_ns / 1e9 <= recent_minutes * 60
        summary, checkpoint, tail_included = _scan_from(
            stream, start_offset=offset, limit=initial.st_size, encoding=encoding,
            initial=saved, include_tail=not recent,
            file_path=log_path, job_date=date, system=system,
        )
        checkpoint["tail_included"] = tail_included
        anchor = _prefix_anchor(stream, checkpoint["offset"])
        if not _snapshot_stable(log_path, stream, initial):
            raise OSError("source changed in place while reading suffix")
    return ParseOutcome(summary, file_signature(initial), checkpoint, anchor,
                        initial.st_size - offset, "append", [initial.st_dev, initial.st_ino])


def parse_changed(log_path: Path, cob: str, system: str, encoding: str,
                  old: dict | None, now: datetime, recent_minutes: int) -> ParseOutcome | None:
    if old is not None:
        result = appended_summary(log_path, cob, system, encoding, old,
                                  now=now, recent_minutes=recent_minutes)
        if result is not None:
            return result
    return stable_summary(log_path, cob, system, encoding, now=now,
                          recent_minutes=recent_minutes)


def update_cob(
    *, cob: str, folder: Path, env_dir: Path, encoding: str,
    delimiter: str, fingerprint: str, policy: IncrementalPolicy,
    now: datetime, force: bool, stdout: TextIO, stderr: TextIO,
    progress: ConsoleProgress | None = None,
) -> CobResult:
    """Return (parsed, cached, skipped, WARN, ERROR, written, closed, removed)."""
    report = env_dir / cob / "jobs.csv"
    state_path = env_dir / ".state" / f"{cob}.json"
    state = load_state(state_path, cob, fingerprint, stderr)
    if state is not None and state["status"] == "closed" and report.is_file() and not force:
        return CobResult(0, 0, 0, 0, 0, 0, 1, 0)

    previous = state.get("files", {}) if state is not None and not force else {}
    parsed = cached = skipped = removed = 0
    full_scans = suffix_scans = bytes_read = 0
    files: dict[str, dict] = {}
    latest_mtime_ns = 0
    paths_found = 0
    status_changes = 0

    # Only a small fixed pool of SMB readers. Prevents flooding the corporate
    # file server and caps open handles, future objects, and memory usage.
    pending: deque[tuple[str, dict | None, Path, Future[ParseOutcome | None]]] = deque()

    def flush_one() -> None:
        nonlocal parsed, skipped, latest_mtime_ns, full_scans, suffix_scans, bytes_read
        key, old, log_path, future = pending.popleft()
        try:
            result = future.result()
            if result is None:
                raise OSError("source was replaced or truncated during parsing; retry next run")
            row = {**vars(result.summary),
                   **activity_fields(result.signature[1], now, policy.recent_minutes),
                   "path": key, "file_size_bytes": result.signature[0],
                   "enrichment_status": "Enriched",
                   "enriched_at_utc": now.astimezone(timezone.utc).isoformat()}
            files[key] = {"signature": result.signature, "row": row,
                          "checkpoint": result.checkpoint, "anchor": result.anchor,
                          "identity": result.identity, "parsed_signature": result.signature}
            parsed += 1
            if progress is not None:
                progress.file_completed("enriched", key)
            bytes_read += result.bytes_read
            if result.mode == "append":
                suffix_scans += 1
            else:
                full_scans += 1
            latest_mtime_ns = max(latest_mtime_ns, result.signature[1])
            if not result.summary.start_time or not result.summary.end_time:
                print(f"WARN: no parseable timestamps in: {log_path}", file=stderr)
            elif not result.summary.duration:
                print(f"WARN: last timestamp precedes first: {log_path}", file=stderr)
        except (OSError, UnicodeError, ValueError) as exc:
            skipped += 1
            if progress is not None:
                progress.file_completed("skipped", key)
            print(f"SKIP: cannot safely read {log_path}: {exc}", file=stderr)
            if old is not None and isinstance(old.get("row"), dict):
                files[key] = old

    # On any directory enumeration failure the context manager drains worker
    # threads, and the exception aborts before publishing any partial report.
    with ThreadPoolExecutor(max_workers=policy.read_workers, thread_name_prefix="smb-log") as pool:
        for log in iter_cob_logs(folder, stderr, progress):
            if log is None:
                skipped += 1
                continue
            paths_found += 1
            log_path, stat, key, system = log.path, log.stat, log.key, log.system
            old = previous.get(key)
            if isinstance(old, dict) and isinstance(old.get("row"), dict):
                old_row = old["row"]
                if "path" not in old_row and "relative_path" in old_row:
                    old_row = {**old_row, "path": old_row.get("relative_path", "")}
                old_row.pop("relative_path", None)
                old = {**old, "row": old_row}
            try:
                signature = file_signature(stat)
                latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
                if (old is not None and isinstance(old, dict)
                    and old.get("signature") == signature and isinstance(old.get("row"), dict)
                    and enrich_status(old["row"]) == "Enriched"
                    and all(field in old["row"] for field in CSV_FIELDS if field not in (
                        "activity_status", "last_modified_time", "path",
                        "file_size_bytes", "enrichment_status", "enriched_at_utc"))
                    and not (isinstance(old.get("checkpoint"), dict)
                             and old["checkpoint"].get("offset", 0) < stat.st_size
                             and not old["checkpoint"].get("tail_included", False)
                             and now.timestamp() - stat.st_mtime_ns / 1e9 > policy.recent_minutes * 60)):
                    new_row = {**old["row"], **activity_fields(stat.st_mtime_ns, now, policy.recent_minutes),
                               "path": key, "file_size_bytes": stat.st_size,
                               "enrichment_status": "Enriched",
                               "enriched_at_utc": old["row"].get("enriched_at_utc", "")}
                    if new_row != old["row"]:
                        status_changes += 1
                    files[key] = {**old, "row": new_row}
                    cached += 1
                    if progress is not None:
                        progress.file_completed("cached", key)
                    continue
                # An inventory run may have refreshed the *observed* metadata.
                # The checkpoint must be compared with the signature captured
                # when content was actually parsed, not the latest directory stat.
                parse_old = ({**old, "signature": old.get("parsed_signature", old.get("signature"))}
                             if isinstance(old, dict) else None)
                future = pool.submit(parse_changed, log_path, cob, system, encoding,
                                     parse_old, now, policy.recent_minutes)
                if progress is not None:
                    progress.file_queued(key)
                pending.append((key, old, log_path, future))
                if len(pending) >= 2 * policy.read_workers:
                    flush_one()
            except (OSError, UnicodeError) as exc:
                skipped += 1
                if progress is not None:
                    progress.file_completed("skipped", key)
                print(f"SKIP: cannot stat {log_path}: {exc}", file=stderr)
                if old is not None and isinstance(old.get("row"), dict):
                    files[key] = old
        while pending:
            flush_one()

    if paths_found == 0:
        if state is not None and report.is_file():
            print(f"WARN: no source logs for {cob}; previous report preserved", file=stderr)
            return CobResult(0, 0, 1, 0, 0, 0, 0, 0)
        return CobResult(0, 0, skipped, 0, 0, 0, 0, 0)

    removed = len(set(previous) - set(files))
    changed = (force or state is None or parsed > 0 or removed > 0 or status_changes > 0
               or not csv_schema_matches(report, delimiter))
    if changed:
        atomic_csv(report, files, delimiter)
        print(f"CSV: {report} ({len(files)} jobs; parsed {parsed}, cached {cached}, removed {removed})", file=stdout)

    age_days = (now.date() - datetime.strptime(cob, "%Y%m%d").date()).days
    quiet_seconds = policy.quiet_hours * 3600
    quiet = latest_mtime_ns > 0 and now.timestamp() - latest_mtime_ns / 1e9 >= quiet_seconds
    close = (age_days >= policy.min_active_days and quiet and skipped == 0 and
             all(enrich_status(entry["row"]) == "Enriched" for entry in files.values()))
    new_state = {
        "version": STATE_VERSION,
        "cob": cob,
        "source_id": fingerprint,
        "status": "closed" if close else "open",
        "last_updated_utc": now.astimezone(timezone.utc).isoformat(),
        "job_count": len(files),
    }
    if not close:
        new_state["files"] = files
    # A no-op refresh should not rewrite multi-thousand-row JSON manifests.
    # Leave the last-updated timestamp unchanged when no data was published.
    if changed or close or state is None:
        atomic_json(state_path, new_state)
    if close:
        print(f"FINALIZED: {cob} (age {age_days} days; quiet >= {policy.quiet_hours} hours)", file=stdout)
    elif not changed:
        print(f"UNCHANGED: {cob} ({cached} cached jobs; report untouched)", file=stdout)

    print(f"I/O: full scans {full_scans}; suffix scans {suffix_scans}; "
          f"payload bytes scanned {bytes_read:,}; workers {policy.read_workers}", file=stdout)
    warnings = sum(int(entry["row"].get("warning_count") or 0) for entry in files.values())
    errors = sum(int(entry["row"].get("error_count") or 0) for entry in files.values())
    return CobResult(parsed, cached, skipped, warnings, errors, int(changed), int(close), removed)


def write_csv(
    *, root: Path, output_dir: Path, environment: str, encoding: str,
    only_date: str | None, delimiter: str,
    stdout: TextIO | None = None, stderr: TextIO | None = None,
    policy: IncrementalPolicy | None = None, force: bool = False,
    now: datetime | None = None,
    mode: str = "enrich",
    progress: ConsoleProgress | None = None,
) -> tuple[int, int, int, int]:
    """Incrementally inventory or enrich open COBs, skip closed trees.

    Return (logs parsed, files skipped, warnings in visited COBs, errors in visited COBs).
    Per-COB manifest caches parsed rows and uses file stat signatures.
    """
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    if not root.is_dir():
        raise ValueError(f"Logs directory does not exist or cannot be accessed: {root}")
    if environment not in ALLOWED_ENVIRONMENTS:
        raise ValueError(f"Unsupported environment: {environment}")
    if len(delimiter) != 1 or delimiter in ('\r', '\n', '"'):
        raise ValueError("CSV delimiter must be one non-newline, non-quote character")
    if mode not in ("inventory", "enrich"):
        raise ValueError("Mode must be inventory or enrich")

    policy = policy if policy is not None else IncrementalPolicy()
    now = now if now is not None else datetime.now().astimezone()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    parsed = cached = skipped = warnings = errors = written = finalized = removed = closed = seen = 0
    root = root.resolve()
    env_target = (output_dir / environment).resolve()
    if env_target.is_relative_to(root) or root.is_relative_to(env_target):
        raise ValueError("Output directory must be separate from and must not contain the source Logs directory")
    fingerprint = source_fingerprint(root, encoding, delimiter)
    env_dir = output_dir / environment
    with environment_lock(env_dir):
        # One root-level directory listing only. Non-COB trees are never
        # traversed, and normal runs touch only the newest configured COBs.
        dates = discover_cobs(
            root, now=now, limit=policy.cob_scan_limit, only_date=only_date,
        )
        if progress is not None:
            progress.discovered(len(dates))
        for cob, folder in dates:
            seen += 1
            if progress is not None:
                progress.begin_cob(cob, seen)
            if mode == "inventory":
                result = inventory_cob(
                    cob=cob, folder=folder, env_dir=env_dir,
                    delimiter=delimiter, fingerprint=fingerprint, policy=policy,
                    now=now, force=force, stdout=stdout, stderr=stderr,
                    progress=progress,
                )
            else:
                result = update_cob(
                    cob=cob, folder=folder, env_dir=env_dir,
                    encoding=encoding, delimiter=delimiter, fingerprint=fingerprint,
                    policy=policy, now=now, force=force, stdout=stdout, stderr=stderr,
                    progress=progress,
                )
            if progress is not None:
                progress.end_cob(closed=bool(result.closed and not result.written),
                                 written=bool(result.written))
            parsed += result.parsed
            cached += result.cached
            skipped += result.skipped
            warnings += result.warnings
            errors += result.errors
            written += result.written
            finalized += result.closed
            removed += result.removed
            if result.closed and not result.written:
                closed += 1

    if seen == 0 or (parsed + cached + closed == 0 and written == 0 and skipped == 0):
        raise ValueError("No logs with a valid business-date folder found; existing CSV reports not replaced")
    print(
        f"Mode: {mode}; Processed: {parsed}; cached: {cached}; skipped: {skipped}; "
        f"removed: {removed}; WARN: {warnings}; ERROR: {errors}; "
        f"COB reports: {written}; finalized: {finalized - closed}; "
        f"skipped closed COBs: {closed}",
        file=stdout,
    )
    return parsed, skipped, warnings, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze recent root-level COB log folders to CSV")
    parser.add_argument("--env", required=True, help="Approved environment: PROD, U5, U1 or U6")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="JSON configuration file")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="Output root directory (default: tools/log_analyzer/output)")
    parser.add_argument("--date", help="Optional root-level COB override, YYYYMMDD (default: latest configured COBs)")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter, comma (default) or semicolon")
    parser.add_argument("--force", action="store_true", help="Reparse selected COB(s), including finalized dates")
    parser.add_argument("--mode", choices=("inventory", "enrich"), default="inventory",
                        help="inventory lists metadata only (default); enrich parses pending/changed log content")
    parser.add_argument("--no-progress", action="store_true",
                        help="Disable interactive dashboard (also automatic when output is redirected)")
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
        config = load_config(args.config)
        root, encoding = resolve_root(args.config, environment, config=config)
        with ConsoleProgress(environment, args.mode, enabled=not args.no_progress) as dashboard:
            _, skipped, _, _ = write_csv(
                root=root, output_dir=args.output_dir, environment=environment, encoding=encoding,
                only_date=args.date, delimiter=args.delimiter,
                policy=policy_from_config(config), force=args.force, mode=args.mode,
                stdout=dashboard.out if dashboard.enabled else sys.stdout,
                stderr=dashboard.err if dashboard.enabled else sys.stderr,
                progress=dashboard if dashboard.enabled else None,
            )
        if dashboard.enabled:
            print(dashboard.final_summary or f"{args.mode.capitalize()} finished for {environment}")
            if dashboard.error_count:
                print(f"Diagnostics: {dashboard.error_count} warnings/skips (last {len(dashboard.errors)} shown):")
                for message in dashboard.errors:
                    print(message, file=sys.stderr)
                print("For all diagnostics, rerun with --no-progress and redirect output to a file.")
        return 2 if skipped else 0
    except (ValueError, OSError, UnicodeError, LookupError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCANCELLED: interrupted by user; previously published COB reports are preserved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
