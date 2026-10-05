"""Identity mapping between AutoSys and Process Scheduler job names."""

from __future__ import annotations

import re
from functools import lru_cache

from app.config import load_identity_map
from app.models import MatchConfidence, SchedulerType, SnapshotJob


@lru_cache
def _pair_map() -> dict[tuple[str, str], str]:
    cfg = load_identity_map()
    mapping: dict[tuple[str, str], str] = {}
    for pair in cfg.pairs:
        logical = f"{pair.autosys_name}|{pair.ps_name}"
        mapping[("autosys", pair.autosys_name)] = logical
        mapping[("process_scheduler", pair.ps_name)] = logical
    return mapping


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
