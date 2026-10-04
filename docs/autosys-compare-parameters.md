# AutoSys reference comparison parameters

Migration parity compares **AutoSys-shaped views** of each job: native JIL + run fields on the AutoSys side, and `autosys_reference` (mapped from Process Scheduler) on the PS side.

## Configuration

Parameter list: `config/autosys_compare_parameters.yaml`

- **jil_parameters** — Broadcom AE JIL attribute names from `insert_job` definitions
- **run_parameters** — autorep-style instance fields (not stored in JIL)
- **timing_threshold_sec** — tolerance for `actual_start` / `actual_end` (default 60)

## Compared parameters (default)

### JIL (`jil` section)

| Parameter | Notes |
|-----------|--------|
| `job_type` | BOX, CMD, FW, … |
| `machine` | Agent; omitted on BOX |
| `box_name` | Parent box |
| `command` | CMD body |
| `watch_file` | FW jobs |
| `condition` | Dependency expression (`s()`, `d()`, …) |
| `date_conditions` | `y` / `n` |
| `start_times` | e.g. `"06:05"` |
| `start_mins` | Offset minutes (FW) |
| `days_of_week` | `all`, `mo,tu,we,th,fr`, … |
| `run_calendar` | Calendar name |
| `timezone` | e.g. `Europe/Zurich` |
| `std_out_file` | stdout log path |
| `std_err_file` | stderr log path |
| `owner` | `user@host` |
| `permission` | ACL string |
| `group` | Job group |
| `application` | Application name |
| `alarm_if_fail` | Alarm flag |
| `max_run_alarm` | Minutes |
| `n_retrys` | Retry count |
| `send_notification` | `Y` / `N` |

### Run instance (`run` section)

| Parameter | Notes |
|-----------|--------|
| `status` | Last run status (raw scheduler string) |
| `resolved_command` | Command after global substitution |
| `actual_start` | Run start timestamp (from snapshot instance) |
| `actual_end` | Run end timestamp |

## Code model

- `app/autosys_reference.py` — `AutoSysJobDefinition`, `AutoSysRunInstance`, `AutoSysJobReference`
- `app/models.py` — `SnapshotJob` carries `autosys: AutoSysJobReference` for topology + compare
- `app/services/comparison.py` — `compare_job_parameters()` / `parameter_mismatches` on `ComparisonResult`

## Samples

- `examples/autosys_jobs.sample.yaml` — native `jil` + `run_instance`
- `examples/process_scheduler_jobs.sample.yaml` — PS-native fields + `autosys_reference` target mapping

See also `docs/job-field-mapping.md` for PS → JIL field mapping notes.
