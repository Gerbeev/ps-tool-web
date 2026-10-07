"""The only application service allowed to read scheduler source systems."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.adapters.factory import get_adapter
from app.config import endpoint_for_environment, get_environment, scheduler_for_environment
from app.models import AsOf, AsOfKind, ComparisonContext, ContextFilters, SchedulerType
from app.services.comparison import fetch_snapshot
from app.services.snapshot_catalog import SnapshotRecord, snapshot_catalog


class SnapshotGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedSnapshot:
    record: SnapshotRecord


def _require_environment(environment_id: str, scheduler: SchedulerType | None = None):
    environment = get_environment(environment_id)
    if environment is None or not environment.enabled:
        raise SnapshotGenerationError(f"Unknown or disabled environment: {environment_id}")
    configured = scheduler_for_environment(environment_id)
    if scheduler is not None and configured != scheduler:
        raise SnapshotGenerationError(
            f"Environment {environment_id!r} is configured for {configured.value}, not {scheduler.value}"
        )
    return environment, configured


def list_process_scheduler_topologies(environment_id: str) -> list[str]:
    """Read topology names from Process Scheduler through the adapter/bridge boundary."""
    _require_environment(environment_id, SchedulerType.PROCESS_SCHEDULER)
    context = ComparisonContext(
        environment_id=environment_id,
        endpoint_url=endpoint_for_environment(environment_id),
        scheduler=SchedulerType.PROCESS_SCHEDULER,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value=date.today().isoformat()),
    )
    try:
        roots = get_adapter(SchedulerType.PROCESS_SCHEDULER, environment_id).list_roots(context)
    except Exception as exc:
        raise SnapshotGenerationError(str(exc)) from exc
    # Preserve source ordering while removing accidental duplicates/blank values.
    return list(dict.fromkeys(item.strip() for item in roots if item and item.strip()))


def generate_snapshot(environment_id: str, *, topology_id: str = "") -> GeneratedSnapshot:
    """Fetch one source snapshot, validate it, then persist it immutably."""
    _environment, scheduler = _require_environment(environment_id)
    today = date.today().isoformat()
    filters = ContextFilters()

    if scheduler == SchedulerType.AUTOSYS:
        if topology_id:
            raise SnapshotGenerationError("AutoSys snapshot generation does not accept a topology")
    else:
        topology_id = topology_id.strip()
        if not topology_id:
            raise SnapshotGenerationError("Select a Process Scheduler topology")
        filters.topology_id = topology_id
        filters.root_box = topology_id

    context = ComparisonContext(
        environment_id=environment_id,
        endpoint_url=endpoint_for_environment(environment_id),
        scheduler=scheduler,
        as_of=AsOf(kind=AsOfKind.BUSINESS_DATE, value=today),
        filters=filters,
    )

    try:
        snapshot, _ = fetch_snapshot(context, force_refresh=True)
    except Exception as exc:
        raise SnapshotGenerationError(str(exc)) from exc

    report = snapshot.metadata.get("validation_report") or {}
    if report.get("is_valid") is False:
        raise SnapshotGenerationError(
            f"Snapshot validation failed ({report.get('error_count', 0)} errors)"
        )

    snapshot.metadata["generated_via"] = "snapshots_tab"
    record = snapshot_catalog.save(snapshot)
    return GeneratedSnapshot(record=record)
