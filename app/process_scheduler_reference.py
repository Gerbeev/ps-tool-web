"""Process Scheduler-native job detail model observed from the endpoint/tool contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProcessSchedulerJobReference(BaseModel):
    """Typed preservation of Process Scheduler job-detail wire fields.

    Field aliases intentionally match the source DTO/tool labels exactly. Unknown future
    fields remain preserved through ``extra='allow'`` so endpoint evolution does not
    silently discard data before the real bank adapter is implemented.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    box: str | None = Field(default=None, alias="Box")
    condition_expression: str | None = Field(default=None, alias="ConditionExpression")
    context: str | None = Field(default=None, alias="Context")
    description: str | None = Field(default=None, alias="Description")
    job_type: str | None = Field(default=None, alias="JobType")
    last_finish_time: datetime | None = Field(default=None, alias="LastFinishTime")
    last_start_time: datetime | None = Field(default=None, alias="LastStartTime")
    name: str | None = Field(default=None, alias="Name")
    owner: str | None = Field(default=None, alias="Owner")
    schedule: str | None = Field(default=None, alias="Schedule")
    start_at_time: str | None = Field(default=None, alias="StartAtTime")
    start_at_time_force: bool | None = Field(default=None, alias="StartAtTimeForce")
    status: str | None = Field(default=None, alias="Status")

    @classmethod
    def from_wire(cls, data: dict[str, Any] | None) -> "ProcessSchedulerJobReference":
        return cls.model_validate(data or {})
