"""Identity mapping between scheduler job names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.config import load_identity_map, load_job_naming_rules
from app.models import MatchConfidence, SchedulerType, SnapshotJob


@dataclass(frozen=True, slots=True)
class ParsedJobName:
    common_prefix: str
    business_code: str
    environment: str
    job_specific_name: str


@lru_cache
def _pair_map() -> dict[tuple[str, str], str]:
    cfg = load_identity_map()
    mapping: dict[tuple[str, str], str] = {}
    for pair in cfg.pairs:
        logical = f"{pair.autosys_name}|{pair.ps_name}"
        mapping[("autosys", pair.autosys_name)] = logical
        mapping[("process_scheduler", pair.ps_name)] = logical
    return mapping


@lru_cache
def _structured_name_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def parse_structured_job_name(name: str) -> ParsedJobName | None:
    """Parse the generic scheduler naming convention, if the name follows it.

    Environment values are deliberately validated structurally rather than against the
    connection catalog. An embedded job-name token may be an environment alias and does
    not have to equal the adapter environment code one-for-one.
    """
    cfg = load_job_naming_rules()
    if cfg is None:
        return None

    pattern = _structured_name_pattern(cfg.parsing.generic_regex)
    match = pattern.fullmatch(name) if cfg.parsing.require_full_match else pattern.match(name)
    if not match:
        return None

    groups = match.groupdict()
    required = {"common_prefix", "business_code", "environment", "job_specific_name"}
    if not required.issubset(groups) or any(groups.get(key) is None for key in required):
        return None

    business_code = groups["business_code"]
    job_specific_name = groups["job_specific_name"]
    if cfg.normalization.trim_outer_whitespace:
        business_code = business_code.strip()
        job_specific_name = job_specific_name.strip()
    if not cfg.normalization.job_specific_name_case_sensitive:
        job_specific_name = job_specific_name.lower()
    if not business_code or not job_specific_name:
        return None

    return ParsedJobName(
        common_prefix=groups["common_prefix"],
        business_code=business_code,
        environment=groups["environment"],
        job_specific_name=job_specific_name,
    )


def structured_logical_id(name: str) -> str | None:
    """Return an environment-independent logical id for a structured job name."""
    parsed = parse_structured_job_name(name)
    if parsed is None:
        return None

    cfg = load_job_naming_rules()
    if cfg is None:
        return None

    identity = cfg.cross_environment_identity
    if identity.require_same_business_code and "business_code" not in identity.include:
        return None

    values = {
        "common_prefix": parsed.common_prefix,
        "business_code": parsed.business_code,
        "environment": parsed.environment,
        "job_specific_name": parsed.job_specific_name,
    }
    try:
        parts = [values[field] for field in identity.include]
    except KeyError:
        return None

    # Namespace the id so it cannot accidentally collide with raw scheduler names or
    # explicit pair ids. The environment token is intentionally absent.
    return "structured:" + "|".join(parts)


def logical_id_for_job(job: SnapshotJob, scheduler: SchedulerType) -> tuple[str | None, MatchConfidence]:
    name = job.scheduler_job_name
    sched_key = scheduler.value
    pairs = _pair_map()
    if (sched_key, name) in pairs:
        return pairs[(sched_key, name)], MatchConfidence.MAPPED

    cfg = load_identity_map()
    if scheduler == SchedulerType.AUTOSYS:
        for rule in cfg.regex_rules:
            if rule.scheduler != "autosys":
                continue
            m = re.match(rule.pattern, name)
            if m:
                ps_name = m.expand(rule.ps_replacement)
                return _normalize_name(ps_name), MatchConfidence.NORMALIZED

    cross_environment_id = structured_logical_id(name)
    if cross_environment_id is not None:
        return cross_environment_id, MatchConfidence.NORMALIZED

    normalized_name = _normalize_name(name)
    if normalized_name != name:
        return normalized_name, MatchConfidence.NORMALIZED

    return normalized_name, MatchConfidence.NAME_ONLY


def _normalize_name(name: str) -> str:
    cfg = load_identity_map()
    result = name
    for prefix in cfg.normalize.strip_prefixes:
        if result.startswith(prefix):
            result = result[len(prefix) :]
    if cfg.normalize.lowercase:
        result = result.lower()
    return result


def annotate_snapshot_jobs(
    jobs: list[SnapshotJob], scheduler: SchedulerType
) -> dict[str, MatchConfidence]:
    confidence_by_uid: dict[str, MatchConfidence] = {}
    for job in jobs:
        lid, confidence = logical_id_for_job(job, scheduler)
        job.logical_id = lid
        confidence_by_uid[job.job_uid] = confidence
    return confidence_by_uid
