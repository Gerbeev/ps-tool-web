"""Reusable self-check for real scheduler adapter implementations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.adapters.base import SchedulerAdapter
from app.models import ComparisonContext, SnapshotValidationIssue, ValidationSeverity
from app.services.identity import annotate_snapshot_jobs
from app.services.snapshot_validation import validate_snapshot


class AdapterContractReport(BaseModel):
    adapter: str
    healthy: bool = False
    snapshot_job_count: int = 0
    snapshot_edge_count: int = 0
    issues: list[SnapshotValidationIssue] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.healthy and not any(
            issue.severity == ValidationSeverity.ERROR for issue in self.issues
        )


def check_adapter_contract(
    adapter: SchedulerAdapter,
    context: ComparisonContext,
) -> AdapterContractReport:
    issues: list[SnapshotValidationIssue] = []
    try:
        healthy = adapter.health_check(context.environment_id)
    except Exception as exc:  # Adapter boundary: report connector failures structurally.
        return AdapterContractReport(
            adapter=type(adapter).__name__,
            healthy=False,
            issues=[
                SnapshotValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="health_check_failed",
                    message=f"{type(exc).__name__}: {exc}",
                )
            ],
        )

    if not healthy:
        issues.append(
            SnapshotValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="health_check_unhealthy",
                message="adapter health_check returned false",
            )
        )
    if context.scheduler != adapter.scheduler_type:
        issues.append(
            SnapshotValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="scheduler_type_mismatch",
                message=(
                    f"context scheduler is {context.scheduler.value!r}, adapter declares "
                    f"{adapter.scheduler_type.value!r}"
                ),
            )
        )

    try:
        snapshot = adapter.fetch_topology(context)
    except Exception as exc:  # Adapter boundary: do not turn connector errors into a traceback-only result.
        issues.append(
            SnapshotValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="fetch_topology_failed",
                message=f"{type(exc).__name__}: {exc}",
            )
        )
        return AdapterContractReport(
            adapter=type(adapter).__name__,
            healthy=healthy,
            issues=issues,
        )

    snapshot.capabilities = adapter.capabilities()
    annotate_snapshot_jobs(snapshot.flat_jobs, context.scheduler)
    if snapshot.context.environment_id != context.environment_id:
        issues.append(
            SnapshotValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="environment_context_mismatch",
                message="snapshot environment_id differs from requested context",
            )
        )
    if snapshot.context.scheduler != adapter.scheduler_type:
        issues.append(
            SnapshotValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="snapshot_scheduler_mismatch",
                message="snapshot scheduler differs from adapter scheduler_type",
            )
        )

    issues.extend(validate_snapshot(snapshot).issues)
    return AdapterContractReport(
        adapter=type(adapter).__name__,
        healthy=healthy,
        snapshot_job_count=len(snapshot.flat_jobs),
        snapshot_edge_count=len(snapshot.edges),
        issues=issues,
    )
