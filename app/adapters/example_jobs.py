"""Load sample job definitions from examples/*.yaml for mocks and tests."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.autosys_reference import (
    AutoSysJobReference,
    reference_from_autosys_row,
    reference_from_ps_row,
)

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _job_name_from_row(row: dict[str, Any]) -> str:
    jil = row.get("jil") or {}
    ref = row.get("autosys_reference") or {}
    ref_jil = ref.get("jil") if isinstance(ref, dict) else {}
    return str(
        jil.get("job_name")
        or (ref_jil.get("job_name") if isinstance(ref_jil, dict) else None)
        or row.get("name")
        or row.get("job_name")
        or ""
    )


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
        path_labels = list(row.get("path") or [_job_name_from_row(row)])
        name = str(row.get("name") or path_labels[-1] or _job_name_from_row(row))
        key = _job_key(name, path_labels)
        out[key] = row
        out[name] = row
        jil_name = (row.get("jil") or {}).get("job_name")
        ref_jil = (row.get("autosys_reference") or {}).get("jil") or {}
        ref_name = ref_jil.get("job_name") if isinstance(ref_jil, dict) else None
        for alias in (jil_name, ref_name):
            if alias and alias not in out:
                out[str(alias)] = row
    return out


def autosys_reference_from_example(
    examples: dict[str, dict[str, Any]],
    name: str,
    path_labels: list[str],
    *,
    actual_start=None,
    actual_end=None,
    status_raw: str | None = None,
    exit_code: int | None = None,
    scheduler: str = "autosys",
) -> AutoSysJobReference:
    row = examples.get(_job_key(name, path_labels)) or examples.get(name)
    if not row:
        return AutoSysJobReference()
    if scheduler == "process_scheduler" or row.get("autosys_reference"):
        return reference_from_ps_row(
            row,
            actual_start=actual_start,
            actual_end=actual_end,
            status_raw=status_raw,
            exit_code=exit_code,
        )
    return reference_from_autosys_row(
        row,
        actual_start=actual_start,
        actual_end=actual_end,
        status_raw=status_raw,
        exit_code=exit_code,
    )
