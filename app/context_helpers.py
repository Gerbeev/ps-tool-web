"""Shared context defaults for browse and compare forms."""

from __future__ import annotations

from datetime import date

from app.adapters.factory import get_adapter
from app.config import endpoint_for_environment, scheduler_for_environment
from app.models import ComparisonContext, ContextFilters, SchedulerType


def default_business_date() -> str:
    return date.today().isoformat()


def topology_options(environment_id: str, scheduler: str | SchedulerType) -> list[str]:
    sched = scheduler if isinstance(scheduler, SchedulerType) else SchedulerType(scheduler)
    if sched != SchedulerType.PROCESS_SCHEDULER:
        return []
    adapter = get_adapter(SchedulerType.PROCESS_SCHEDULER, environment_id)
    ctx = ComparisonContext(environment_id=environment_id, scheduler=SchedulerType.PROCESS_SCHEDULER)
    return adapter.list_roots(ctx)


def scheduler_label(scheduler: str) -> str:
    if scheduler == SchedulerType.PROCESS_SCHEDULER.value:
        return "Process Scheduler"
    return "AutoSys"


def parse_browse_context(
    environment_id: str,
    scheduler: str,
    as_of: str,
    topology: str,
) -> ComparisonContext:
    sched = SchedulerType(scheduler)
    filters = ContextFilters()
    if sched == SchedulerType.PROCESS_SCHEDULER and topology:
        filters.topology_id = topology
        filters.root_box = topology
    elif sched == SchedulerType.AUTOSYS:
        filters.root_box = "RISK_DAILY_BOX"
    return ComparisonContext(
        environment_id=environment_id,
        endpoint_url=endpoint_for_environment(environment_id),
        scheduler=sched,
        as_of=_as_of(as_of),
        filters=filters,
    )


def parse_compare_side_context(
    environment_id: str,
    scheduler: str,
    as_of: str,
    topology: str,
    root_box: str | None = None,
) -> ComparisonContext:
    sched = SchedulerType(scheduler)
    filters = ContextFilters()
    if sched == SchedulerType.PROCESS_SCHEDULER:
        topo = topology or root_box or ""
        if topo:
            filters.topology_id = topo
            filters.root_box = topo
    elif sched == SchedulerType.AUTOSYS:
        filters.root_box = root_box or "RISK_DAILY_BOX"
    return ComparisonContext(
        environment_id=environment_id,
        endpoint_url=endpoint_for_environment(environment_id),
        scheduler=sched,
        as_of=_as_of(as_of or default_business_date()),
        filters=filters,
    )


def _as_of(value: str):
    from app.models import AsOf, AsOfKind

    return AsOf(kind=AsOfKind.BUSINESS_DATE, value=value or default_business_date())


def environment_scheduler_value(environment_id: str) -> str:
    return scheduler_for_environment(environment_id).value
