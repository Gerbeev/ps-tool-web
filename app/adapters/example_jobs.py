"""Load sample job definitions from examples/*.yaml for mocks and tests."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.models import JobSchedule

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

_WEEKDAY_CRON: dict[str, str] = {
    "all": "*",
    "mo,tu,we,th,fr": "1-5",
    "mo-fr": "1-5",
    "sa,su": "0,6",
}


def _job_name_from_row(row: dict[str, Any]) -> str:
    jil = row.get("jil") or {}
    return str(jil.get("job_name") or row.get("name") or row.get("job_name") or "")


def _job_key(name: str, path_labels: list[str]) -> str:
    return "/".join(path_labels) if path_labels else name


@lru_cache(maxsize=2)
def load_autosys_example_jobs() -> dict[str, dict[str, Any]]:
    return _load_jobs_file(_EXAMPLES_DIR / "autosys_jobs.sample.yaml")


@lru_cache(maxsize=2)
def load_ps_example_jobs() -> dict[str, dict[str, Any]]:
    return _load_jobs_file(_EXAMPLES_DIR / "process_scheduler_jobs.sample.yaml")


def _load_jobs_file(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    jobs = data.get("jobs") or []
    out: dict[str, dict[str, Any]] = {}
    for row in jobs:
        path_labels = row.get("path") or [_job_name_from_row(row)]
        name = _job_name_from_row(row) or str(path_labels[-1])
        key = _job_key(name, path_labels)
        out[key] = row
        out[name] = row
    return out


def _cron_from_start_times(start_times: str, days_of_week: str | None) -> str | None:
    raw = (start_times or "").strip().strip('"')
    if not raw:
        return None
    # JIL start_times: "HH:MM" or "HH:MM,HH:MM" — use first slot for parity cron
    first = raw.split(",")[0].strip()
    parts = first.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    dow_key = (days_of_week or "all").strip().lower().replace(" ", "")
    dow = _WEEKDAY_CRON.get(dow_key, "*")
    return f"{minute} {hour} * * {dow}"


def schedule_from_jil(jil: dict[str, Any]) -> JobSchedule | None:
    if not jil:
        return None
    date_cond = str(jil.get("date_conditions", "n")).strip().lower()
    uses_dates = date_cond in {"y", "1", "yes", "true"}
    run_calendar = jil.get("run_calendar")
    timezone = jil.get("timezone")
    days = jil.get("days_of_week")

    if jil.get("start_mins") is not None and not jil.get("start_times"):
        return JobSchedule(
            raw=f"start_mins: {jil['start_mins']}",
            calendar=run_calendar,
            timezone=timezone,
        )

    if not uses_dates:
        raw = jil.get("schedule_raw") or "date_conditions: n"
        return JobSchedule(raw=str(raw), calendar=run_calendar, timezone=timezone)

    expression = _cron_from_start_times(str(jil.get("start_times") or ""), days)
    if expression:
        return JobSchedule(
            expression=expression,
            calendar=run_calendar,
            timezone=timezone,
        )
    return JobSchedule(calendar=run_calendar, timezone=timezone, raw="date_conditions: y")


def schedule_from_row(row: dict[str, Any] | None) -> JobSchedule | None:
    if not row:
        return None
    jil = row.get("jil")
    if isinstance(jil, dict) and jil:
        return schedule_from_jil(jil)
    sched = row.get("schedule")
    if not sched:
        return None
    if isinstance(sched, str):
        return JobSchedule(raw=sched)
    return JobSchedule(
        expression=sched.get("expression"),
        calendar=sched.get("calendar"),
        timezone=sched.get("timezone"),
        raw=sched.get("raw"),
    )


def _command_from_jil(jil: dict[str, Any]) -> str | None:
    if jil.get("command"):
        return str(jil["command"])
    if jil.get("watch_file"):
        return str(jil["watch_file"])
    return None


def _log_paths_from_jil(jil: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("std_out_file", "std_err_file"):
        val = jil.get(key)
        if val:
            paths.append(str(val))
    return paths


def definition_from_example(
    examples: dict[str, dict[str, Any]],
    name: str,
    path_labels: list[str],
) -> dict[str, Any]:
    row = examples.get(_job_key(name, path_labels)) or examples.get(name)
    if not row:
        return {}

    jil = row.get("jil") if isinstance(row.get("jil"), dict) else {}
    run_instance = row.get("run_instance") if isinstance(row.get("run_instance"), dict) else {}

    if jil:
        resolved_command = run_instance.get("resolved_command")
        if resolved_command is None and run_instance.get("resolved_watch_file"):
            resolved_command = run_instance.get("resolved_watch_file")
        gv = run_instance.get("global_variables") or {}
        return {
            "schedule": schedule_from_jil(jil),
            "command": _command_from_jil(jil),
            "condition": jil.get("condition"),
            "log_paths": _log_paths_from_jil(jil),
            "resolved_command": resolved_command,
            "resolved_parameters": dict(gv),
            "machine": jil.get("machine"),
            "box_name": jil.get("box_name"),
            "job_type": str(jil.get("job_type") or "").lower() or None,
            "jil_attributes": {
                k: v
                for k, v in jil.items()
                if k
                not in {
                    "job_name",
                    "job_type",
                    "command",
                    "condition",
                    "machine",
                    "box_name",
                    "watch_file",
                    "std_out_file",
                    "std_err_file",
                    "start_times",
                    "start_mins",
                    "days_of_week",
                    "run_calendar",
                    "date_conditions",
                    "timezone",
                }
            },
        }

    return {
        "schedule": schedule_from_row(row),
        "command": row.get("command"),
        "condition": row.get("condition"),
        "log_paths": list(row.get("log_paths") or []),
        "resolved_command": row.get("resolved_command"),
        "resolved_parameters": dict(row.get("resolved_parameters") or {}),
    }
