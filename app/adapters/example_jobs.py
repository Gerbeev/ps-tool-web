"""Load sample job definitions from examples/*.yaml for mocks and tests."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.models import JobSchedule

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


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
        path_labels = row.get("path") or [row["name"]]
        key = _job_key(row["name"], path_labels)
        out[key] = row
        out[row["name"]] = row
    return out


def schedule_from_row(row: dict[str, Any] | None) -> JobSchedule | None:
    if not row:
        return None
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


def definition_from_example(
    examples: dict[str, dict[str, Any]],
    name: str,
    path_labels: list[str],
) -> dict[str, Any]:
    row = examples.get(_job_key(name, path_labels)) or examples.get(name)
    if not row:
        return {}
    return {
        "schedule": schedule_from_row(row),
        "command": row.get("command"),
        "condition": row.get("condition"),
        "log_paths": list(row.get("log_paths") or []),
        "resolved_command": row.get("resolved_command"),
        "resolved_parameters": dict(row.get("resolved_parameters") or {}),
    }
