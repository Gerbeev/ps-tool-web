"""Mock Process Scheduler adapter for local development and contract tests."""

from __future__ import annotations

from app.adapters.base import SchedulerAdapter
from app.adapters.mock_data import build_ps_snapshot, list_ps_topology_names
from app.models import ComparisonContext, SchedulerType, SnapshotJob, TopologySnapshot


class ProcessSchedulerMockAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.PROCESS_SCHEDULER

    def health_check(self, environment_id: str) -> bool:
        return bool(environment_id)

    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        return build_ps_snapshot(context)

    def fetch_job_detail(self, context: ComparisonContext, job_uid: str) -> SnapshotJob | None:
        snap = self.fetch_topology(context)
        for job in snap.flat_jobs:
            if job.job_uid == job_uid:
                return job
        return None

    def list_roots(self, context: ComparisonContext) -> list[str]:
        return list_ps_topology_names()
