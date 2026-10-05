"""Mock AutoSys adapter for local development and contract tests."""

from __future__ import annotations

from app.adapters.base import SchedulerAdapter
from app.adapters.mock_data import build_autosys_snapshot
from app.models import ComparisonContext, SchedulerType, SnapshotJob, TopologySnapshot


class AutoSysMockAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.AUTOSYS

    def health_check(self, environment_id: str) -> bool:
        return bool(environment_id)

    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        snap = build_autosys_snapshot(context)
        return snap

    def fetch_job_detail(self, context: ComparisonContext, job_uid: str) -> SnapshotJob | None:
        snap = self.fetch_topology(context)
        for job in snap.flat_jobs:
            if job.job_uid == job_uid:
                return job
        return None

    def list_roots(self, context: ComparisonContext) -> list[str]:
        return ["RISK_DAILY_BOX"]
