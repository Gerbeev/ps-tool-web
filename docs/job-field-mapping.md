# Process Scheduler → AutoSys JIL mapping

Reference model: `AutoSysJobReference` (`app/autosys_reference.py`) on each `SnapshotJob`.

Comparison uses **official AutoSys JIL / run attribute names** — not a parallel normalized schema. Process Scheduler adapters map migrated job definitions into `autosys_reference` (see `examples/process_scheduler_jobs.sample.yaml`).

## Identity (unchanged)

| Concept | AutoSys | Process Scheduler |
|---------|---------|-------------------|
| Logical pairing | `config/identity_map.yaml` | Same map |
| Path | box / job path | topology / job path |

## Definition mapping (PS native → JIL reference)

| JIL parameter | Process Scheduler source (typical) |
|---------------|-------------------------------------|
| `job_type` | PS job type → CMD / FW / BOX equivalent |
| `machine` | Agent / host binding |
| `box_name` | Parent topology / box name |
| `command` | Script / .NET command line |
| `watch_file` | File-wait path |
| `condition` | Dependency → `s()` / `d()` AutoSys expression |
| `date_conditions` | `y` when schedule active |
| `start_times` | Cron / schedule → `HH:MM` |
| `start_mins` | Offset minutes |
| `days_of_week` | Cron DOW → `all` / `mo,tu,...` |
| `run_calendar` | Calendar id |
| `timezone` | Job timezone |
| `std_out_file` / `std_err_file` | Log path list |
| `owner`, `permission`, `group`, `application` | Metadata from migration target |

## Run instance mapping

| Run parameter | Source |
|---------------|--------|
| `status` | Native run status string |
| `resolved_command` | Command after `{BusinessDate}` / `$${GLOBAL}` substitution |
| `actual_start` / `actual_end` | Instance timestamps on snapshot |

Full compare list: `docs/autosys-compare-parameters.md` and `config/autosys_compare_parameters.yaml`.
