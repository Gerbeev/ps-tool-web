"""Runtime duration helpers shared by models, UI, and exports."""

from __future__ import annotations

from datetime import datetime


def execution_time_seconds(start: datetime | None, end: datetime | None) -> float | None:
    """Return execution duration derived from actual timestamps, or None when incomplete/invalid."""
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return seconds


def format_duration_hms(seconds: float | int | None, *, signed: bool = False) -> str:
    """Format a duration as HH:MM:SS without wrapping hours at 24."""
    if seconds is None:
        return ""
    value = int(round(float(seconds)))
    sign = ""
    if value < 0:
        sign = "-"
        value = abs(value)
    elif signed and value > 0:
        sign = "+"

    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"
