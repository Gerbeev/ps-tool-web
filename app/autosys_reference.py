"""AutoSys-native reference model for migration parity comparison."""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings


_JOB_TYPE_ALIASES = {
    "B": "BOX",
    "BOX": "BOX",
    "C": "CMD",
    "CMD": "CMD",
    "F": "FW",
    "FW": "FW",
}

_BOOLEAN_PARAMETERS = {
    "alarm_if_fail",
    "alarm_if_terminated",
    "auto_hold",
    "box_terminator",
    "date_conditions",
    "job_terminator",
}

_SET_PARAMETERS = {
    "start_times",
    "start_mins",
    "success_codes",
    "fail_codes",
    "notification_alarm_types",
}

_CONDITION_FUNCTION_ALIASES = {
    "success": "s",
    "failure": "f",
    "done": "d",
    "terminated": "t",
    "notrunning": "n",
    "exitcode": "e",
}


class AutoSysJobDefinition(BaseModel):
    """JIL job definition attributes used by migration parity checks.

    Known high-value attributes are typed explicitly. Unknown JIL attributes are
    preserved so real AutoSys definitions are not silently truncated and can be
    enabled later through the comparison configuration without changing the model.
    """

    model_config = ConfigDict(extra="allow")

    job_name: str | None = None
    job_type: str | None = None
    machine: str | None = None
    box_name: str | None = None
    command: str | None = None
    watch_file: str | None = None
    condition: str | None = None

    # Date/time scheduling.
    date_conditions: int | str | bool | None = None
    start_times: str | None = None
    start_mins: int | str | None = None
    days_of_week: str | None = None
    run_calendar: str | None = None
    exclude_calendar: str | None = None
    run_window: str | None = None
    must_start_times: str | None = None
    must_complete_times: str | None = None
    timezone: str | None = None

    # Execution environment / output.
    std_out_file: str | None = None
    std_err_file: str | None = None
    owner: str | None = None
    permission: str | None = None
    group: str | None = None
    application: str | None = None
    description: str | None = None
    profile: str | None = None
    envvars: str | list[str] | dict[str, Any] | None = None
    priority: int | str | None = None
    resources: str | None = None

    # Completion / exit-code semantics.
    success_codes: str | int | None = None
    fail_codes: str | int | None = None
    n_retrys: int | str | None = None

    # Box behavior.
    box_success: str | None = None
    box_failure: str | None = None
    box_terminator: int | str | bool | None = None
    job_terminator: int | str | bool | None = None

    # File Watcher behavior.
    watch_interval: int | str | None = None
    watch_file_min_size: int | str | None = None

    # Runtime controls / alarms / notifications.
    alarm_if_fail: int | str | bool | None = None
    alarm_if_terminated: int | str | bool | None = None
    min_run_alarm: int | str | None = None
    max_run_alarm: int | str | None = None
    term_run_time: int | str | None = None
    send_notification: str | int | bool | None = None
    notification_id: str | None = None
    notification_msg: str | None = None
    notification_template: str | None = None
    notification_alarm_types: str | list[str] | None = None
    auto_hold: int | str | bool | None = None
    auto_delete: int | str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> AutoSysJobDefinition:
        return cls(**(data or {}))

    def raw_parameter_value(self, parameter: str) -> Any:
        if parameter == "exit_code_policy":
            return self.exit_code_policy()
        if parameter in type(self).model_fields:
            return getattr(self, parameter)
        return (self.model_extra or {}).get(parameter)

    def exit_code_policy(self) -> str:
        """Return effective command exit-code classification policy."""
        fail_codes = _normalize_set(self.fail_codes)
        if fail_codes:
            return f"fail:{fail_codes}"
        success_codes = _normalize_set(self.success_codes)
        if success_codes:
            return f"success:{success_codes}"
        return "success:0"


class AutoSysRunInstance(BaseModel):
    """Runtime/autorep-style fields (not stored in the static JIL definition)."""

    model_config = ConfigDict(extra="allow")

    status: str | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    resolved_command: str | None = None
    resolved_watch_file: str | None = None
    global_variables: dict[str, Any] = Field(default_factory=dict)
    exit_code: int | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> AutoSysRunInstance:
        return cls(**(data or {}))

    def raw_parameter_value(self, parameter: str) -> Any:
        if parameter in type(self).model_fields:
            return getattr(self, parameter)
        return (self.model_extra or {}).get(parameter)


class AutoSysJobReference(BaseModel):
    jil: AutoSysJobDefinition = Field(default_factory=AutoSysJobDefinition)
    run: AutoSysRunInstance = Field(default_factory=AutoSysRunInstance)

    def parameter_value(self, parameter: str) -> str:
        if parameter == "exit_code_policy" or parameter in AutoSysJobDefinition.model_fields:
            return normalize_parameter_value(parameter, self.jil.raw_parameter_value(parameter))
        if parameter in AutoSysRunInstance.model_fields:
            val = self.run.raw_parameter_value(parameter)
            if isinstance(val, datetime):
                return val.isoformat()
            return normalize_parameter_value(parameter, val)

        # Preserve/compare extra fields from either block if explicitly enabled in config.
        jil_extra = (self.jil.model_extra or {}).get(parameter)
        if jil_extra is not None:
            return normalize_parameter_value(parameter, jil_extra)
        run_extra = (self.run.model_extra or {}).get(parameter)
        return normalize_parameter_value(parameter, run_extra)


class CompareParametersConfig(BaseModel):
    timing_threshold_sec: float = 60.0
    jil_parameters: list[str] = Field(default_factory=list)
    run_parameters: list[str] = Field(default_factory=list)

    @property
    def all_parameters(self) -> list[str]:
        return list(self.jil_parameters) + list(self.run_parameters)


@lru_cache(maxsize=1)
def load_compare_parameters() -> CompareParametersConfig:
    config_path = get_settings().config_dir / "autosys_compare_parameters.yaml"
    if not config_path.is_file():
        return CompareParametersConfig(
            jil_parameters=["job_type", "command", "condition", "start_times"],
            run_parameters=["resolved_command", "actual_start", "actual_end"],
        )
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CompareParametersConfig(**data)


def normalize_parameter_value(parameter: str, value: Any) -> str:
    """Canonicalize AutoSys values where syntax differs but semantics do not."""
    if parameter == "job_type":
        raw = _norm_value(value).upper()
        return _JOB_TYPE_ALIASES.get(raw, raw or "CMD")
    if parameter == "send_notification":
        return _normalize_send_notification(value)
    if parameter in _BOOLEAN_PARAMETERS:
        return _normalize_bool(value)
    if parameter == "condition" or parameter in {"box_success", "box_failure"}:
        return _normalize_condition(value)
    if parameter == "days_of_week":
        return _normalize_days(value)
    if parameter in _SET_PARAMETERS:
        return _normalize_set(value)
    if parameter == "watch_file_min_size" and value in (None, ""):
        return "0"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return ";".join(f"{k}={value[k]}" for k in sorted(value))
    if isinstance(value, list):
        return ";".join(str(v).strip() for v in value)
    return _norm_value(value)


def _norm_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_bool(value: Any) -> str:
    raw = _norm_value(value).lower()
    if raw in {"1", "y", "yes", "true", "t"}:
        return "true"
    if raw in {"0", "n", "no", "false", "f", ""}:
        return "false"
    return raw


def _normalize_send_notification(value: Any) -> str:
    """Canonicalize AutoSys notification mode without collapsing failure-only to false."""
    raw = _norm_value(value).lower()
    if raw in {"", "0", "n", "no", "none", "false"}:
        return "0" if raw else ""
    if raw in {"1", "y", "yes", "true", "t"}:
        return "1"
    if raw in {"2", "f", "failure"}:
        return "2"
    return raw


def _normalize_set(value: Any) -> str:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    tokens: list[str] = []
    for item in values:
        raw = _norm_value(item)
        if raw:
            tokens.extend(token.strip() for token in raw.split(",") if token.strip())
    if not tokens:
        return ""

    def sort_key(token: str) -> tuple[int, int | str]:
        if token.isdigit():
            return (0, int(token))
        return (1, token.lower())

    return ",".join(sorted(dict.fromkeys(tokens), key=sort_key))


def _normalize_days(value: Any) -> str:
    raw = _norm_value(value).lower()
    if not raw:
        return ""
    aliases = {
        "sun": "su",
        "sunday": "su",
        "mon": "mo",
        "monday": "mo",
        "tue": "tu",
        "tues": "tu",
        "tuesday": "tu",
        "wed": "we",
        "wednesday": "we",
        "thu": "th",
        "thur": "th",
        "thurs": "th",
        "thursday": "th",
        "fri": "fr",
        "friday": "fr",
        "sat": "sa",
        "saturday": "sa",
    }
    if raw == "all":
        return "all"
    days = {aliases.get(token.strip(), token.strip()) for token in raw.split(",") if token.strip()}
    order = ["su", "mo", "tu", "we", "th", "fr", "sa"]
    if days == set(order):
        return "all"
    known = [day for day in order if day in days]
    unknown = sorted(day for day in days if day not in order)
    return ",".join([*known, *unknown])


def _normalize_condition(value: Any) -> str:
    raw = _norm_value(value)
    if not raw:
        return ""

    normalized = raw
    for long_name, short_name in _CONDITION_FUNCTION_ALIASES.items():
        normalized = re.sub(
            rf"\b{long_name}\s*(?=\()",
            short_name,
            normalized,
            flags=re.IGNORECASE,
        )
    normalized = re.sub(r"\bAND\b", "&", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bOR\b", "|", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*([(),&|=<>!])\s*", r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def validate_autosys_definition(definition: AutoSysJobDefinition) -> list[str]:
    """Return deterministic semantic warnings for high-value AutoSys JIL rules."""
    issues: list[str] = []
    job_type = normalize_parameter_value("job_type", definition.job_type)

    if definition.start_times not in (None, "") and definition.start_mins not in (None, ""):
        issues.append("start_times and start_mins are mutually exclusive")
    if definition.days_of_week not in (None, "") and definition.run_calendar not in (None, ""):
        issues.append("days_of_week and run_calendar are mutually exclusive")

    has_must_time = any(
        value not in (None, "")
        for value in (definition.must_start_times, definition.must_complete_times)
    )
    has_start_time = any(
        value not in (None, "") for value in (definition.start_times, definition.start_mins)
    )
    if has_must_time and (
        normalize_parameter_value("date_conditions", definition.date_conditions) != "true"
        or not has_start_time
    ):
        issues.append(
            "must_start_times/must_complete_times require date_conditions and start_times/start_mins"
        )

    if job_type == "CMD" and not _norm_value(definition.command):
        issues.append("CMD job has no command")
    if job_type == "FW" and not _norm_value(definition.watch_file):
        issues.append("FW job has no watch_file")
    if job_type != "BOX" and any(
        _norm_value(value) for value in (definition.box_success, definition.box_failure)
    ):
        issues.append("box_success/box_failure are only meaningful for BOX jobs")
    if _normalize_bool(definition.box_terminator) == "true" and not _norm_value(definition.box_name):
        issues.append("box_terminator requires box_name")
    if _norm_value(definition.notification_template) and _norm_value(definition.notification_msg):
        issues.append("notification_template and notification_msg are mutually exclusive")

    return issues


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


def compare_reference_parameter(
    left: AutoSysJobReference,
    right: AutoSysJobReference,
    parameter: str,
    *,
    timing_threshold_sec: float = 60.0,
) -> tuple[str, str, bool]:
    """Compare one normalized AutoSys-equivalent field."""
    lv = left.parameter_value(parameter)
    rv = right.parameter_value(parameter)
    if parameter in ("actual_start", "actual_end"):
        return lv, rv, _times_within_threshold(lv, rv, timing_threshold_sec)
    return lv, rv, lv == rv


def compare_references(
    left: AutoSysJobReference,
    right: AutoSysJobReference,
    *,
    logical_id: str | None = None,
    config: CompareParametersConfig | None = None,
) -> list[tuple[str, str, str]]:
    """Return list of (parameter, left_value, right_value) semantic mismatches."""
    del logical_id  # Reserved for future per-job policy; kept for API compatibility.
    cfg = config or load_compare_parameters()
    out: list[tuple[str, str, str]] = []
    for param in cfg.all_parameters:
        lv, rv, equal = compare_reference_parameter(
            left, right, param, timing_threshold_sec=cfg.timing_threshold_sec
        )
        if not equal:
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
