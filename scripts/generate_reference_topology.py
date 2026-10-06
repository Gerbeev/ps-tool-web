from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "mock" / "reference_topology_2500.jsonl"
OVERLAY_OUTPUT = ROOT / "data" / "mock" / "u1_to_u5_migration_overlay.jsonl"

COMMON_PREFIX = "IB_CT_CVA_"
REFERENCE_SCHEDULE = "Tuesday,Wednesday,Thursday,Friday,Saturday"
REFERENCE_START_AT_TIME = "00:01"
BUSINESS_CODES = [f"{4000 + i:04d}" for i in range(1, 26)]
SECTIONS = [
    "Admin",
    "Audit",
    "DP_ADP",
    "DP_IM",
    "DS_FG",
    "Reports",
    "QuarterEnd",
    "Reconciliation",
    "Publishing",
]
TASKS = [
    ("File_Watcher", "FW", "file_watch"),
    ("Extract", "CMD", "command"),
    ("Transform", "CMD", "dotnet"),
    ("Load", "CMD", "command"),
    ("Validate", "CMD", "command"),
    ("StoredProc", "CMD", "stored_procedure"),
    ("Reconcile", "CMD", "command"),
    ("Report", "CMD", "report"),
    ("Archive", "CMD", "command"),
    ("Publish", "CMD", "publisher"),
]

# Small but varied, deterministic migration-defect population for the U1 -> U5 demo.
SCENARIO_COUNTS = {
    "missing": 12,
    "failed": 18,
    "long_running": 10,
    "activated": 12,
    "waiting": 8,
    "on_ice": 6,
    "cancelled": 4,
    "late_success": 15,
    "command_drift": 5,
    "machine_drift": 5,
    "schedule_drift": 3,
    "dependency_removed": 4,
}


def _command(semantic_type: str, business_code: str, specific_name: str) -> str | None:
    if semantic_type == "file_watch":
        return None
    if semantic_type == "dotnet":
        return (
            "C:/DataPlatform/TransformationEngine.Host.exe "
            f"--business={business_code} --job={specific_name}"
        )
    if semantic_type == "stored_procedure":
        return f"sqlcmd -Q EXEC dbo.Run_{specific_name} @BusinessCode={business_code}"
    if semantic_type == "report":
        return f"C:/DataPlatform/ReportRunner.exe --business={business_code} --report={specific_name}"
    if semantic_type == "publisher":
        return f"C:/DataPlatform/Publisher.exe --business={business_code} --job={specific_name}"
    return f"C:/DataPlatform/BatchRunner.exe --business={business_code} --job={specific_name}"


def _description(semantic_type: str, business_code: str, section: str, task_name: str) -> str:
    descriptions = {
        "file_watch": f"Waits for the {section} inbound readiness marker for business application {business_code}.",
        "dotnet": f"Runs the {section} transformation stage for business application {business_code} using the .NET transformation host.",
        "stored_procedure": f"Executes the {section} database processing step for business application {business_code}.",
        "report": f"Generates the {section} reporting output for business application {business_code}.",
        "publisher": f"Publishes the completed {section} output for business application {business_code}.",
        "command": f"Executes the {section} {task_name.lower().replace('_', ' ')} batch step for business application {business_code}.",
    }
    return descriptions.get(
        semantic_type,
        f"Executes the {section} workflow step for business application {business_code}.",
    )


def _base_record(
    *,
    job_ref: str,
    business_code: str,
    job_specific_name: str,
    parent_ref: str | None,
    job_type: str,
    semantic_type: str,
    start_offset_sec: int,
    duration_sec: int,
    machine: str | None,
    command: str | None,
    watch_file: str | None,
    depends_on: list[str],
    description: str,
) -> dict[str, Any]:
    return {
        "record_type": "job",
        "job_ref": job_ref,
        "business_code": business_code,
        "common_prefix": COMMON_PREFIX,
        "job_specific_name": job_specific_name,
        "parent_ref": parent_ref,
        "job_type": job_type,
        "semantic_type": semantic_type,
        "status": "success",
        "machine": machine,
        "command": command,
        "watch_file": watch_file,
        "start_offset_sec": start_offset_sec,
        "duration_sec": duration_sec,
        "exit_code": 0,
        "depends_on": depends_on,
        "timezone": "London",
        "owner": "svc_batch",
        "permission": "mx,gx",
        "group": f"BUSINESS_{business_code}",
        "application": f"APP_{business_code}",
        "description": description,
        "schedule": REFERENCE_SCHEDULE,
        "start_at_time": REFERENCE_START_AT_TIME,
        "start_at_time_force": False,
    }


def generate() -> list[dict[str, Any]]:
    """Generate a healthy AutoSys-style baseline with realistic, varied runtimes.

    Each business group starts shortly after midnight with deterministic jitter. Leaf
    jobs are chained and begin after their predecessor finishes, while section/root
    box runtime windows contain their children. The canonical fixture is deliberately
    healthy; migration defects are applied separately through the U5 overlay.
    """
    records: list[dict[str, Any]] = []

    for group_index, business_code in enumerate(BUSINESS_CODES, start=1):
        root_ref = f"business-{business_code}/root"
        group_start = 60 + (group_index - 1) * 19  # 00:01:00..00:08:36 across groups
        cursor = group_start + 25
        previous_task_ref: str | None = None
        section_payloads: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

        for section_index, section in enumerate(SECTIONS, start=1):
            box_ref = f"business-{business_code}/{section.lower()}-box"
            task_records: list[dict[str, Any]] = []
            section_start = cursor - 8

            for task_index, (task_name, job_type, semantic_type) in enumerate(TASKS, start=1):
                specific_name = f"{section}_{task_name}"
                job_ref = (
                    f"business-{business_code}/{section.lower()}/"
                    f"{task_index:02d}-{task_name.lower()}"
                )
                duration_sec = 35 + (
                    (group_index * 17 + section_index * 29 + task_index * 31) % 210
                )
                start_gap_sec = 4 + (
                    (group_index * 7 + section_index * 5 + task_index * 3) % 23
                )
                start_offset_sec = cursor + start_gap_sec
                cursor = start_offset_sec + duration_sec

                watch_file = None
                if semantic_type == "file_watch":
                    watch_file = f"C:/DataPlatform/in/{business_code}/{section}.ready"

                task_records.append(
                    _base_record(
                        job_ref=job_ref,
                        business_code=business_code,
                        job_specific_name=specific_name,
                        parent_ref=box_ref,
                        job_type=job_type,
                        semantic_type=semantic_type,
                        start_offset_sec=start_offset_sec,
                        duration_sec=duration_sec,
                        machine=f"mock-batch-{((group_index + section_index) % 4) + 1:02d}",
                        command=_command(semantic_type, business_code, specific_name),
                        watch_file=watch_file,
                        depends_on=[previous_task_ref] if previous_task_ref else [],
                        description=_description(semantic_type, business_code, section, task_name),
                    )
                )
                previous_task_ref = job_ref

            section_end = cursor + 12
            box_record = _base_record(
                job_ref=box_ref,
                business_code=business_code,
                job_specific_name=f"{section}_Box",
                parent_ref=root_ref,
                job_type="BOX",
                semantic_type="box",
                start_offset_sec=section_start,
                duration_sec=section_end - section_start,
                machine=None,
                command=None,
                watch_file=None,
                depends_on=[],
                description=f"Groups and controls the {section} workflow for business application {business_code}.",
            )
            section_payloads.append((box_record, task_records))
            cursor += 20 + ((group_index + section_index) % 31)

        root_start = group_start
        root_end = cursor + 20
        records.append(
            _base_record(
                job_ref=root_ref,
                business_code=business_code,
                job_specific_name="Application_Box",
                parent_ref=None,
                job_type="BOX",
                semantic_type="box",
                start_offset_sec=root_start,
                duration_sec=root_end - root_start,
                machine=None,
                command=None,
                watch_file=None,
                depends_on=[],
                description=f"Coordinates the complete batch workflow for business application {business_code}.",
            )
        )
        for box_record, task_records in section_payloads:
            records.append(box_record)
            records.extend(task_records)

    return records


def _take_distributed(
    candidates: list[dict[str, Any]],
    *,
    count: int,
    start: int,
    step: int,
    used: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    index = start % len(candidates)
    visited = 0
    while len(selected) < count:
        record = candidates[index]
        ref = str(record["job_ref"])
        if ref not in used:
            used.add(ref)
            selected.append(record)
        index = (index + step) % len(candidates)
        visited += 1
        if visited > len(candidates) * 4:
            raise RuntimeError(f"Could not select {count} unique scenario records")
    return selected


def _issue_records(
    selected: Iterable[dict[str, Any]], issue_type: str, **payload: Any
) -> list[dict[str, Any]]:
    return [
        {
            "record_type": "issue",
            "issue_type": issue_type,
            "job_ref": record["job_ref"],
            **payload,
        }
        for record in selected
    ]


def generate_migration_overlay(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaves = [r for r in records if r["job_type"] != "BOX"]
    command_jobs = [r for r in leaves if r.get("command")]
    dependency_jobs = [r for r in leaves if r.get("depends_on")]
    used: set[str] = set()
    issues: list[dict[str, Any]] = []

    selectors = [
        ("missing", leaves, 11, 173, {}),
        ("failed", leaves, 67, 181, {"status": "failure", "raw_status": "Failed", "exit_code": 8}),
        ("long_running", leaves, 131, 191, {"status": "running", "raw_status": "Running", "start_shift_sec": 25, "clear_end": True, "exit_code": None}),
        ("activated", leaves, 211, 197, {"status": "pending", "raw_status": "Activated", "clear_start": True, "clear_end": True, "exit_code": None}),
        ("waiting", leaves, 277, 199, {"status": "pending", "raw_status": "Waiting", "clear_start": True, "clear_end": True, "exit_code": None}),
        ("on_ice", leaves, 349, 211, {"status": "disabled", "raw_status": "OnIce", "clear_start": True, "clear_end": True, "exit_code": None}),
        ("cancelled", leaves, 421, 223, {"status": "killed", "raw_status": "Cancelled", "exit_code": 143}),
        ("late_success", leaves, 503, 227, {"start_shift_sec": 420, "end_shift_sec": 420}),
        ("command_drift", command_jobs, 587, 229, {"command_suffix": " --migration-mode=compat"}),
        ("machine_drift", leaves, 641, 233, {"machine": "mock-migrated-batch-99"}),
        ("schedule_drift", leaves, 733, 239, {"schedule": "Monday,Tuesday,Wednesday,Thursday,Friday"}),
        ("dependency_removed", dependency_jobs, 811, 241, {"remove_incoming_dependency": True}),
    ]

    for issue_type, candidates, start, step, payload in selectors:
        selected = _take_distributed(
            candidates,
            count=SCENARIO_COUNTS[issue_type],
            start=start,
            step=step,
            used=used,
        )
        issues.extend(_issue_records(selected, issue_type, **payload))

    if len(used) != sum(SCENARIO_COUNTS.values()):
        raise RuntimeError("Scenario selections unexpectedly overlap")
    return issues


def _write_jsonl(path: Path, metadata: dict[str, Any], records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(metadata, separators=(",", ":")) + "\n")
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def main() -> None:
    records = generate()
    if len(records) != 2500:
        raise RuntimeError(f"Expected exactly 2500 jobs, got {len(records)}")

    meta = {
        "record_type": "metadata",
        "schema_version": 4,
        "dataset_id": "reference_topology_2500",
        "job_count": len(records),
        "business_group_count": len(BUSINESS_CODES),
        "common_prefix": COMMON_PREFIX,
        "environment_neutral": True,
        "healthy_baseline": True,
        "name_template": "{common_prefix}{business_code}_{ENV}_{job_specific_name}",
        "topology_id": "DataPlatform_REFERENCE",
        "notes": "Deterministic healthy surrogate baseline. All canonical jobs succeed with varied realistic runtimes; environment-specific migration defects are applied by a separate overlay.",
    }
    _write_jsonl(OUTPUT, meta, records)

    overlay = generate_migration_overlay(records)
    overlay_meta = {
        "record_type": "metadata",
        "schema_version": 1,
        "scenario_id": "u1_autosys_to_u5_process_scheduler_migration",
        "baseline_scheduler": "autosys",
        "baseline_environment": "U1",
        "target_scheduler": "process_scheduler",
        "target_environment": "U5",
        "normal_target_start_shift_sec": 25,
        "issue_count": len(overlay),
        "issue_counts": SCENARIO_COUNTS,
        "notes": "Deterministic synthetic migration defects layered onto the healthy canonical fixture. Missing jobs are removed from the U5 snapshot; other issues remain inspectable in Browse and Compare.",
    }
    _write_jsonl(OVERLAY_OUTPUT, overlay_meta, overlay)

    print(f"wrote {OUTPUT} ({len(records)} healthy baseline jobs)")
    print(f"wrote {OVERLAY_OUTPUT} ({len(overlay)} injected migration issues)")


if __name__ == "__main__":
    main()
