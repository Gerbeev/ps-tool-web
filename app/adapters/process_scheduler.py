"""Mock Process Scheduler adapter for Phase 2 demos."""

from __future__ import annotations

from app.adapters.base import SchedulerAdapter
from app.adapters.mock_data import build_ps_snapshot
from app.models import ComparisonContext, NormalizedJob, SchedulerType, TopologySnapshot


class ProcessSchedulerMockAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.PROCESS_SCHEDULER

    def health_check(self, environment_id: str) -> bool:
        return bool(environment_id)

    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        return build_ps_snapshot(context)

    def fetch_job_detail(self, context: ComparisonContext, job_uid: str) -> NormalizedJob | None:
        snap = self.fetch_topology(context)
        for job in snap.flat_jobs:
            if job.job_uid == job_uid:
                return job
        return None

    def list_roots(self, context: ComparisonContext) -> list[str]:
        return ["risk_daily_topology"]
