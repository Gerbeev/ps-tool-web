"""Comparison table row materialization and paging."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ComparisonResult, JobPair, ParameterMismatch, SnapshotJob


@dataclass(frozen=True)
class TableRow:
    kind: str  # pair | left_only | right_only
    logical_id: str
    pair: JobPair | None = None
    job: SnapshotJob | None = None

    @property
    def is_mismatch_row(self) -> bool:
        if self.kind == "left_only" or self.kind == "right_only":
            return True
        if self.pair and self.pair.left and self.pair.right:
            return self.pair.left.status != self.pair.right.status
        return False


def parameter_mismatches_by_logical_id(
    result: ComparisonResult,
) -> dict[str, list[ParameterMismatch]]:
    grouped: dict[str, list[ParameterMismatch]] = {}
    for mismatch in result.parameter_mismatches:
        if mismatch.logical_id:
            grouped.setdefault(mismatch.logical_id, []).append(mismatch)
    return grouped


def parameter_mismatches_for_pair(
    result: ComparisonResult, logical_id: str | None
) -> list[ParameterMismatch]:
    if not logical_id:
        return []
    return [
        mismatch
        for mismatch in result.parameter_mismatches
        if mismatch.logical_id == logical_id
    ]


def iter_table_rows(
    result: ComparisonResult,
    *,
    filter_name: str = "all",
    q_prefix: str = "",
) -> list[TableRow]:
    prefix = q_prefix.strip().lower()
    rows: list[TableRow] = []
    parameter_mismatch_ids = {
        mismatch.logical_id
        for mismatch in result.parameter_mismatches
        if mismatch.logical_id
    }

    def name_matches(job: SnapshotJob | None) -> bool:
        if not prefix or not job:
            return True
        return job.scheduler_job_name.lower().startswith(prefix) or (
            (job.logical_id or "").lower().startswith(prefix)
        )

    if filter_name in ("all", "matched", "mismatches", "status_delta"):
        for pair in result.pairs:
            if filter_name == "status_delta" and (
                not pair.left or not pair.right or pair.left.status == pair.right.status
            ):
                continue
            if filter_name == "mismatches" and pair.left and pair.right:
                has_param_delta = pair.logical_id in parameter_mismatch_ids
                if pair.left.status == pair.right.status and not has_param_delta:
                    continue
            if not name_matches(pair.left) and not name_matches(pair.right):
                continue
            rows.append(
                TableRow(
                    kind="pair",
                    logical_id=pair.logical_id or "",
                    pair=pair,
                )
            )

    if filter_name in ("all", "mismatches", "left_only"):
        for job in result.left_only:
            if not name_matches(job):
                continue
            rows.append(
                TableRow(
                    kind="left_only",
                    logical_id=job.logical_id or job.scheduler_job_name,
                    job=job,
                )
            )

    if filter_name in ("all", "mismatches", "right_only"):
        for job in result.right_only:
            if not name_matches(job):
                continue
            rows.append(
                TableRow(
                    kind="right_only",
                    logical_id=job.logical_id or job.scheduler_job_name,
                    job=job,
                )
            )

    return rows


def page_table_rows(
    rows: list[TableRow],
    *,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[TableRow], int]:
    total = len(rows)
    if offset < 0:
        offset = 0
    if limit is None or limit <= 0:
        return rows[offset:], total
    return rows[offset : offset + limit], total
