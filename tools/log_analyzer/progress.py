#!/usr/bin/env python3
"""Dependency-free, bounded terminal dashboard for inventory/enrichment runs.

All source-file operations remain in analyze.py; this module writes only to the
local terminal and never touches or locks any source log.
"""

from __future__ import annotations

from collections import deque
import os
import re
import shutil
import sys
import threading
import time
from typing import TextIO


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _safe(value: object) -> str:
    return _CONTROL.sub(" ", str(value)).strip()


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _terminal_size(stream: TextIO) -> tuple[int, int]:
    """Return the size of the actual output console, not an unrelated stdout."""
    try:
        columns, lines = os.get_terminal_size(stream.fileno())
    except (AttributeError, OSError, ValueError):
        columns, lines = shutil.get_terminal_size(fallback=(100, 26))
    return max(20, columns), max(10, lines)


def _fit(text: object, width: int, *, keep_tail: bool = False) -> str:
    """Fit one logical dashboard row into one physical console row."""
    value = _safe(text)
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    if keep_tail and width >= 12:
        tail = width - 4
        return "... " + value[-tail:]
    return value[: width - 3] + "..."


def _compact_event(message: str, width: int) -> str:
    """Keep diagnostics useful without allowing UNC paths to dominate the UI."""
    value = _safe(message)
    if len(value) <= width:
        return value

    # Most long diagnostics end with a path. Preserve the diagnostic prefix and
    # the useful tail of that path rather than the repeated UNC root.
    marker = value.rfind(": ")
    if marker > 0:
        prefix = value[: marker + 2]
        remaining = width - len(prefix)
        if remaining >= 16:
            return prefix + _fit(value[marker + 2 :], remaining, keep_tail=True)
    return _fit(value, width, keep_tail=True)


def _enable_windows_vt() -> tuple[object, int] | None:
    """Enable ANSI escape sequences in native Windows consoles, if available."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL
    stdout_handle = kernel32.GetStdHandle(-11)
    if stdout_handle in (0, ctypes.c_void_p(-1).value):
        raise OSError("no console output handle")
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
        raise OSError("output is not a Windows console")
    original = mode.value
    # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
    if not kernel32.SetConsoleMode(stdout_handle, original | 0x0001 | 0x0004):
        raise OSError("virtual terminal sequences not supported")
    return stdout_handle, original


def _restore_windows_mode(handle_and_mode: tuple[object, int] | None) -> None:
    if handle_and_mode is None:
        return
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode(*handle_and_mode)


class _CapturedOutput:
    """A line-oriented TextIO sink: messages become dashboard events."""

    def __init__(self, board: ConsoleProgress, *, error: bool) -> None:
        self.board = board
        self.error = error
        self.pending = ""

    def write(self, text: str) -> int:
        self.pending += str(text)
        if "\n" in self.pending:
            lines = self.pending.split("\n")
            self.pending = lines.pop()
            for line in lines:
                self.board.message(line, error=self.error)
        return len(text)

    def flush(self) -> None:
        if self.pending:
            self.board.message(self.pending, error=self.error)
            self.pending = ""


class ConsoleProgress:
    """Single-screen progress with clock-driven updates even during long file reads.

    The file total is exact for the currently enumerated COB; other COBs are
    counted by date, never by a costly extra SMB scan of all log contents.
    """

    def __init__(self, environment: str, mode: str, *, stream: TextIO | None = None,
                 refresh_interval: float = 0.25, enabled: bool = True) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.enabled = bool(enabled and getattr(self.stream, "isatty", lambda: False)())
        self.environment = _safe(environment)
        self.mode = _safe(mode).upper()
        self.refresh_interval = refresh_interval
        self.out = _CapturedOutput(self, error=False)
        self.err = _CapturedOutput(self, error=True)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.windows_mode: tuple[object, int] | None = None
        self.start_time = time.monotonic()
        self.cob_start_time = self.start_time
        self.stage = "Discovering COB folders"
        self.current_cob = "-"
        self.cob_index = 0
        self.cob_total = 0
        self.file_total: int | None = None
        self.file_done = 0
        self.overall_files = 0
        self.in_flight: set[str] = set()
        self.parsed = 0
        self.inventoried = 0
        self.cached = 0
        self.skipped = 0
        self.closed = 0
        self.reports = 0
        self.last_file = "-"
        self.events: deque[str] = deque(maxlen=6)
        self.errors: deque[str] = deque(maxlen=5)
        self.error_count = 0
        self.final_summary = ""
        self.finished = False
        self._last_frame = ""

    def __enter__(self) -> ConsoleProgress:
        if not self.enabled:
            return self
        try:
            self.windows_mode = _enable_windows_vt()
            self.stream.write("\x1b[?1049h\x1b[?25l\x1b[H\x1b[2J")
            self.stream.flush()
        except (OSError, AttributeError):
            _restore_windows_mode(self.windows_mode)
            self.windows_mode = None
            self.enabled = False
            return self
        self.thread = threading.Thread(target=self._ticker, name="console-progress", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.enabled:
            return
        self.out.flush()
        self.err.flush()
        with self.lock:
            self.finished = True
            self.stage = "Finished" if exc_type is None else "Interrupted / Failed"
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            self._render(force=True)
        finally:
            try:
                self.stream.write("\x1b[?25h\x1b[?1049l")
                self.stream.flush()
            finally:
                _restore_windows_mode(self.windows_mode)

    def _ticker(self) -> None:
        while not self.stop.is_set():
            try:
                self._render()
            except (OSError, ValueError):
                self.stop.set()
                return
            self.stop.wait(self.refresh_interval)

    def discovered(self, cob_total: int) -> None:
        with self.lock:
            self.cob_total = cob_total
            self.stage = "Preparing COB inventory"

    def begin_cob(self, cob: str, index: int) -> None:
        with self.lock:
            self.current_cob = _safe(cob)
            self.cob_index = index
            self.cob_start_time = time.monotonic()
            self.stage = "Reading COB file metadata"
            self.file_total = None
            self.file_done = 0
            self.last_file = "-"
            self.in_flight.clear()

    def set_file_total(self, total: int) -> None:
        with self.lock:
            self.file_total = total
            self.stage = "Inventory" if self.mode == "INVENTORY" else "Enriching"

    def file_queued(self, filename: str) -> None:
        with self.lock:
            self.last_file = _safe(filename)
            self.in_flight.add(filename)

    def file_completed(self, kind: str, filename: str) -> None:
        with self.lock:
            self.in_flight.discard(filename)
            self.file_done += 1
            self.overall_files += 1
            self.last_file = _safe(filename)
            if kind == "enriched":
                self.parsed += 1
            elif kind == "inventoried":
                self.inventoried += 1
            elif kind == "cached":
                self.cached += 1
            elif kind == "skipped":
                self.skipped += 1

    def end_cob(self, *, closed: bool = False, written: bool = False) -> None:
        with self.lock:
            self.closed += int(closed)
            self.reports += int(written)
            if closed:
                self.stage = "Previously finalized COB skipped"
            elif self.file_total is not None:
                self.file_done = max(self.file_done, self.file_total)
                self.stage = "COB complete"

    def message(self, message: str, *, error: bool) -> None:
        message = _safe(message)
        if not message:
            return
        with self.lock:
            if message.startswith("Mode:"):
                self.final_summary = message
            if error and (message.startswith(("WARN:", "SKIP:", "ERROR:"))):
                self.error_count += 1
                self.errors.append(message)
            # I/O counters are already represented by the dashboard statistics.
            # Repeating them in Recent events creates noise and very long rows.
            if not message.startswith("I/O:"):
                self.events.append(message)

    def _render(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.start_time
            cob_elapsed = now - self.cob_start_time
            total, done = self.file_total, self.file_done
            columns, height = _terminal_size(self.stream)
            # Leave two columns unused. Some Windows console hosts auto-wrap when
            # the final visible column is written, which corrupts the next row.
            width = max(18, columns - 2)
            bar_width = max(8, min(36, width - 29))
            pct = min(1.0, done / total) if total else 0.0
            filled = round(bar_width * pct)
            bar = "#" * filled + "." * (bar_width - filled)
            percentage = f"{pct * 100:5.1f}%" if total is not None and total > 0 else "  n/a"
            count = f"{done:,} / {total:,}" if total is not None else f"{done:,} / counting..."
            rate = done / cob_elapsed if cob_elapsed > 0 else 0.0
            eta = (_duration((total - done) / rate)
                   if total is not None and done > 0 and cob_elapsed >= 1.0 and rate > 0 else "calculating")
            if total is not None and done >= total:
                eta = "00:00:00"
            # Approximate overall ETA based on COBs completed plus the current
            # COB fraction; no second pass through the source tree is needed.
            completed_units = max(0, self.cob_index - 1) + pct
            overall_eta = (_duration(elapsed * (self.cob_total - completed_units) / completed_units)
                           if elapsed >= 1 and completed_units > 0 and self.cob_total else "calculating")
            if self.cob_total and self.cob_index == self.cob_total and total is not None and done >= total:
                overall_eta = "00:00:00"
            prefix = " Last file     : "
            queue_suffix = f"  |  Queued reads: {len(self.in_flight)}"
            last_file_width = max(1, width - len(prefix) - len(queue_suffix))
            last_file = _fit(self.last_file, last_file_width, keep_tail=True)

            lines = [
                f" JOB LOG ANALYZER  |  {self.environment}  |  {self.mode}",
                "=" * min(68, width),
                f" Stage         : {self.stage}",
                f" COB           : {self.current_cob}  ({self.cob_index:,}/{self.cob_total:,})",
                f" Progress      : [{bar}] {percentage}",
                f" COB files     : {count}",
                f" This COB      : {rate:,.1f} files/s  |  ETA {eta}",
                f" All COBs ETA  : {'~' + overall_eta if overall_eta != 'calculating' else overall_eta}",
                f" Total handled : {self.overall_files:,}  |  Enriched: {self.parsed:,}  |  Inventoried: {self.inventoried:,}",
                f" Cached        : {self.cached:,}  |  Skipped: {self.skipped:,}  |  Closed: {self.closed:,}",
                f" Elapsed       : {_duration(elapsed)}  |  Reports: {self.reports:,}",
                prefix + last_file + queue_suffix,
                "-" * min(68, width),
                " Recent events:",
            ]
            available = max(0, height - len(lines) - 1)
            if available:
                event_width = max(1, width - 2)
                events = list(self.events)[-min(available, 4):]
                lines.extend("  " + _compact_event(event, event_width) for event in events)

            # Fit every logical row explicitly. Never rely on the terminal host
            # to wrap; a wrapped row would shift the whole dashboard downward.
            text = "\n".join(_fit(line, width) for line in lines[:height])
            if not force and text == self._last_frame:
                return
            self._last_frame = text
            # Always reset to the upper-left corner of the alternate screen.
            self.stream.write("\x1b[H\x1b[2J" + text)
            self.stream.flush()
