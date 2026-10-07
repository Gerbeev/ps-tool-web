"""Scheduler adapter ABC and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import (
    AdapterCapabilities,
    ComparisonContext,
    FieldSupport,
    SchedulerType,
    SnapshotJob,
    TopologySnapshot,
)


class SchedulerAdapter(ABC):
    """Boundary between scheduler-specific retrieval and the comparison engine.

    Mock adapters return engine snapshots directly. Real bank connectivity is isolated
    behind ``ExternalBridgeAdapter`` and scheduler-bridge/v1.
    """

    scheduler_type: SchedulerType

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities()

    @abstractmethod
    def health_check(self, environment_id: str) -> bool:
        """Quick availability check for API/CLI."""

    @abstractmethod
    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        """Load tree, flat job list, real dependency edges, and normalized fields."""

    @abstractmethod
    def fetch_job_detail(
        self, context: ComparisonContext, job_uid: str
    ) -> SnapshotJob | None:
        """Optional lazy load of extended job fields."""

    def list_roots(self, context: ComparisonContext) -> list[str]:
        """Box/topology roots for UI selection."""
        return []


def complete_parameter_support(
    default: FieldSupport = FieldSupport.SUPPORTED,
    *,
    overrides: dict[str, FieldSupport] | None = None,
) -> dict[str, FieldSupport]:
    """Return an explicit support declaration for every engine comparison field."""
    from app.autosys_reference import load_compare_parameters

    parameters = set(load_compare_parameters().all_parameters)
    parameters.update({"status", "dependencies", "topology_parent"})
    support = {parameter: default for parameter in parameters}
    support.update(overrides or {})
    return support
