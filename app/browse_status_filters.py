"""Browse tree status filter options — aligned with JobStatus."""

from __future__ import annotations

from app.models import JobStatus

# Non-terminal / idle states grouped as "Inactive" in the toolbar (excludes success, failure, running).
BROWSE_STATUS_INACTIVE: frozenset[JobStatus] = frozenset(
    {
        JobStatus.PENDING,
        JobStatus.NOT_RUN,
        JobStatus.DISABLED,
        JobStatus.KILLED,
        JobStatus.UNKNOWN,
    }
)

BROWSE_STATUS_INACTIVE_VALUES: tuple[str, ...] = tuple(
    sorted(status.value for status in BROWSE_STATUS_INACTIVE)
)

BROWSE_STATUS_LABELS: dict[JobStatus, str] = {
    JobStatus.SUCCESS: "Success",
    JobStatus.FAILURE: "Failure",
    JobStatus.RUNNING: "Running",
    JobStatus.PENDING: "Pending",
    JobStatus.NOT_RUN: "Not run",
    JobStatus.DISABLED: "Disabled",
    JobStatus.KILLED: "Killed",
    JobStatus.UNKNOWN: "Unknown",
}

# Dropdown order (common outcomes first, then idle / non-terminal states).
BROWSE_STATUS_FILTER_ORDER: tuple[JobStatus, ...] = (
    JobStatus.SUCCESS,
    JobStatus.FAILURE,
    JobStatus.RUNNING,
    JobStatus.PENDING,
    JobStatus.NOT_RUN,
    JobStatus.DISABLED,
    JobStatus.KILLED,
    JobStatus.UNKNOWN,
)
