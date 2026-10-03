"""Scheduler adapter ABC and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import ComparisonContext, NormalizedJob, SchedulerType, TopologySnapshot


class SchedulerAdapter(ABC):
    scheduler_type: SchedulerType

    @abstractmethod
    def health_check(self, environment_id: str) -> bool:
        """Quick availability check for API/CLI."""

    @abstractmethod
    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        """Load tree and flat job list for the given context."""

    @abstractmethod
    def fetch_job_detail(
        self, context: ComparisonContext, job_uid: str
    ) -> NormalizedJob | None:
        """Optional lazy load of extended job fields."""

    def list_roots(self, context: ComparisonContext) -> list[str]:
        """Box/topology roots for UI selection."""
        return []
