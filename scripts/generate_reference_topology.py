from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "mock" / "reference_topology_2500.jsonl"

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


def _status(global_ordinal: int) -> str:
    marker = global_ordinal % 20
    if marker == 0:
        return "failure"
    if marker == 1:
        return "running"
    if marker == 2:
        return "pending"
    if marker == 3:
        return "disabled"
    if marker == 4:
        return "killed"
    return "success"


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


def generate() -> list[dict]:
    records: list[dict] = []
    global_task_ordinal = 0

    for group_index, business_code in enumerate(BUSINESS_CODES, start=1):
        root_ref = f"business-{business_code}/root"
        records.append(
            {
                "record_type": "job",
                "job_ref": root_ref,
                "business_code": business_code,
                "common_prefix": COMMON_PREFIX,
                "job_specific_name": "Application_Box",
                "parent_ref": None,
                "job_type": "BOX",
                "semantic_type": "box",
                "status": "success",
                "machine": None,
                "command": None,
                "watch_file": None,
                "start_offset_sec": group_index * 60,
                "duration_sec": 7200,
                "exit_code": 0,
                "depends_on": [],
                "timezone": "London",
                "owner": "svc_batch",
                "permission": "mx,gx",
                "group": f"BUSINESS_{business_code}",
                "application": f"APP_{business_code}",
                "description": "Synthetic application root box",
                "schedule": REFERENCE_SCHEDULE,
                "start_at_time": REFERENCE_START_AT_TIME,
                "start_at_time_force": False,
            }
        )

        previous_task_ref: str | None = None
        for section_index, section in enumerate(SECTIONS, start=1):
            box_ref = f"business-{business_code}/{section.lower()}-box"
            records.append(
                {
                    "record_type": "job",
                    "job_ref": box_ref,
                    "business_code": business_code,
                    "common_prefix": COMMON_PREFIX,
                    "job_specific_name": f"{section}_Box",
                    "parent_ref": root_ref,
                    "job_type": "BOX",
                    "semantic_type": "box",
                    "status": "success",
                    "machine": None,
                    "command": None,
                    "watch_file": None,
                    "start_offset_sec": group_index * 60 + section_index * 30,
                    "duration_sec": 3600,
                    "exit_code": 0,
                    "depends_on": [],
                    "timezone": "London",
                    "owner": "svc_batch",
                    "permission": "mx,gx",
                    "group": f"BUSINESS_{business_code}",
                    "application": f"APP_{business_code}",
                    "description": f"Synthetic {section} section box",
                    "schedule": REFERENCE_SCHEDULE,
                    "start_at_time": REFERENCE_START_AT_TIME,
                    "start_at_time_force": False,
                }
            )

            for task_index, (task_name, job_type, semantic_type) in enumerate(TASKS, start=1):
                global_task_ordinal += 1
                specific_name = f"{section}_{task_name}"
                job_ref = f"business-{business_code}/{section.lower()}/{task_index:02d}-{task_name.lower()}"
                status = _status(global_task_ordinal)
                duration_sec = 45 + ((group_index * 13 + section_index * 7 + task_index * 11) % 900)
                start_offset_sec = (
                    group_index * 60
                    + section_index * 180
                    + task_index * 60
                )
                exit_code = 0
                if status == "failure":
                    exit_code = 8
                elif status == "killed":
                    exit_code = 143
                elif status in {"running", "pending", "disabled"}:
                    exit_code = None

                watch_file = None
                if semantic_type == "file_watch":
                    watch_file = f"C:/DataPlatform/in/{business_code}/{section}.ready"

                records.append(
                    {
                        "record_type": "job",
                        "job_ref": job_ref,
                        "business_code": business_code,
                        "common_prefix": COMMON_PREFIX,
                        "job_specific_name": specific_name,
                        "parent_ref": box_ref,
                        "job_type": job_type,
                        "semantic_type": semantic_type,
                        "status": status,
                        "machine": f"mock-batch-{((group_index + section_index) % 4) + 1:02d}",
                        "command": _command(semantic_type, business_code, specific_name),
                        "watch_file": watch_file,
                        "start_offset_sec": start_offset_sec,
                        "duration_sec": duration_sec,
                        "exit_code": exit_code,
                        "depends_on": [previous_task_ref] if previous_task_ref else [],
                        "timezone": "London",
                        "owner": "svc_batch",
                        "permission": "mx,gx",
                        "group": f"BUSINESS_{business_code}",
                        "application": f"APP_{business_code}",
                        "description": f"Synthetic {semantic_type} job",
                        "schedule": REFERENCE_SCHEDULE,
                        "start_at_time": REFERENCE_START_AT_TIME,
                        "start_at_time_force": False,
                    }
                )
                previous_task_ref = job_ref

    return records


def main() -> None:
    records = generate()
    if len(records) != 2500:
        raise RuntimeError(f"Expected exactly 2500 jobs, got {len(records)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "record_type": "metadata",
        "schema_version": 2,
        "dataset_id": "reference_topology_2500",
        "job_count": len(records),
        "business_group_count": len(BUSINESS_CODES),
        "common_prefix": COMMON_PREFIX,
        "environment_neutral": True,
        "name_template": "{common_prefix}{business_code}_{ENV}_{job_specific_name}",
        "topology_id": "DataPlatform_REFERENCE",
        "notes": "Deterministic surrogate fixture based on observed scheduler naming/tree/runtime shapes; contains no bank endpoint data.",
    }
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(meta, separators=(",", ":")) + "\n")
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    print(f"wrote {OUTPUT} ({len(records)} jobs)")


if __name__ == "__main__":
    main()
