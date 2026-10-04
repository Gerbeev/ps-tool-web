"""AutoSys-native reference model for migration parity comparison."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "autosys_compare_parameters.yaml"


class AutoSysJobDefinition(BaseModel):
    """JIL job definition attributes (official AutoSys names)."""

    job_name: str | None = None
    job_type: str | None = None
    machine: str | None = None
    box_name: str | None = None
    command: str | None = None
    watch_file: str | None = None
    condition: str | None = None
    date_conditions: str | None = None
    start_times: str | None = None
    start_mins: int | str | None = None
    days_of_week: str | None = None
    run_calendar: str | None = None
    timezone: str | None = None
    std_out_file: str | None = None
    std_err_file: str | None = None
    owner: str | None = None
    permission: str | None = None
    group: str | None = None
    application: str | None = None
    alarm_if_fail: int | str | None = None
    max_run_alarm: int | str | None = None
    n_retrys: int | str | None = None
    send_notification: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> AutoSysJobDefinition:
        if not data:
            return cls()
        known = cls.model_fields.keys()
        payload = {k: v for k, v in data.items() if k in known}
        return cls(**payload)


class AutoSysRunInstance(BaseModel):
    """autorep-style run instance fields (not stored in JIL)."""

    status: str | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    resolved_command: str | None = None
    resolved_watch_file: str | None = None
    global_variables: dict[str, Any] = Field(default_factory=dict)
    exit_code: int | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> AutoSysRunInstance:
        if not data:
            return cls()
        known = cls.model_fields.keys()
        payload = {k: v for k, v in data.items() if k in known}
        return cls(**payload)


class AutoSysJobReference(BaseModel):
    jil: AutoSysJobDefinition = Field(default_factory=AutoSysJobDefinition)
    run: AutoSysRunInstance = Field(default_factory=AutoSysRunInstance)

    def parameter_value(self, parameter: str) -> str:
        if parameter in AutoSysJobDefinition.model_fields:
            return _norm_value(getattr(self.jil, parameter))
        if parameter in AutoSysRunInstance.model_fields:
            val = getattr(self.run, parameter)
            if isinstance(val, datetime):
                return val.isoformat()
            return _norm_value(val)
        return ""


class CompareParametersConfig(BaseModel):
    timing_threshold_sec: float = 60.0
    jil_parameters: list[str] = Field(default_factory=list)
    run_parameters: list[str] = Field(default_factory=list)

    @property
    def all_parameters(self) -> list[str]:
        return list(self.jil_parameters) + list(self.run_parameters)


@lru_cache(maxsize=1)
def load_compare_parameters() -> CompareParametersConfig:
    if not _CONFIG_PATH.is_file():
        return CompareParametersConfig(
            jil_parameters=["command", "condition", "start_times"],
            run_parameters=["status", "resolved_command"],
        )
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CompareParametersConfig(**data)


def _norm_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def reference_from_autosys_row(
    row: dict[str, Any],
    *,
    actual_start: datetime | None = None,
    actual_end: datetime | None = None,
    status_raw: str | None = None,
    exit_code: int | None = None,
) -> AutoSysJobReference:
    jil = row.get("jil") if isinstance(row.get("jil"), dict) else {}
    run_row = row.get("run_instance") if isinstance(row.get("run_instance"), dict) else {}
    run = AutoSysRunInstance.from_mapping(run_row)
    if status_raw and not run.status:
        run.status = status_raw
    if actual_start is not None:
        run.actual_start = actual_start
    if actual_end is not None:
        run.actual_end = actual_end
    if exit_code is not None:
        run.exit_code = exit_code
    if run.resolved_command is None and run.resolved_watch_file:
        run.resolved_command = run.resolved_watch_file
    return AutoSysJobReference(jil=AutoSysJobDefinition.from_mapping(jil), run=run)


def reference_from_ps_row(
    row: dict[str, Any],
    *,
    actual_start: datetime | None = None,
    actual_end: datetime | None = None,
    status_raw: str | None = None,
    exit_code: int | None = None,
) -> AutoSysJobReference:
    block = row.get("autosys_reference")
    if not isinstance(block, dict):
        return AutoSysJobReference()
    jil = block.get("jil") if isinstance(block.get("jil"), dict) else {}
    run_row = block.get("run") if isinstance(block.get("run"), dict) else {}
    ref = AutoSysJobReference(
        jil=AutoSysJobDefinition.from_mapping(jil),
        run=AutoSysRunInstance.from_mapping(run_row),
    )
    if status_raw and not ref.run.status:
        ref.run.status = status_raw
    if actual_start is not None:
        ref.run.actual_start = actual_start
    if actual_end is not None:
        ref.run.actual_end = actual_end
    if exit_code is not None:
        ref.run.exit_code = exit_code
    if ref.run.resolved_command is None and ref.run.resolved_watch_file:
        ref.run.resolved_command = ref.run.resolved_watch_file
    return ref


def compare_references(
    left: AutoSysJobReference,
    right: AutoSysJobReference,
    *,
    logical_id: str | None = None,
    config: CompareParametersConfig | None = None,
) -> list[tuple[str, str, str]]:
    """Return list of (parameter, left_value, right_value) mismatches."""
    cfg = config or load_compare_parameters()
    threshold = cfg.timing_threshold_sec
    out: list[tuple[str, str, str]] = []
    for param in cfg.all_parameters:
        lv = left.parameter_value(param)
        rv = right.parameter_value(param)
        if param in ("actual_start", "actual_end"):
            if not _times_within_threshold(lv, rv, threshold):
                out.append((param, lv, rv))
        elif lv != rv:
            out.append((param, lv, rv))
    return out


def _times_within_threshold(left: str, right: str, threshold_sec: float) -> bool:
    if not left and not right:
        return True
    if not left or not right:
        return False
    try:
        ld = datetime.fromisoformat(left.replace("Z", "+00:00"))
        rd = datetime.fromisoformat(right.replace("Z", "+00:00"))
    except ValueError:
        return left == right
    if ld.tzinfo is None and rd.tzinfo is not None:
        ld = ld.replace(tzinfo=rd.tzinfo)
    if rd.tzinfo is None and ld.tzinfo is not None:
        rd = rd.replace(tzinfo=ld.tzinfo)
    return abs((ld - rd).total_seconds()) <= threshold_sec
