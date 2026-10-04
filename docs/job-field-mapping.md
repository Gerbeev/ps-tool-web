# Job field mapping: AutoSys ↔ Process Scheduler

Unified model: `NormalizedJob` in `app/models.py`.

Sample payloads: `examples/autosys_jobs.sample.yaml` (JIL-shaped definitions + `run_instance`), `examples/process_scheduler_jobs.sample.yaml` (PS definition parity).

## Source of truth by scheduler

| Layer | AutoSys (CA WA / Broadcom AE) | Process Scheduler (in-house) |
|-------|-------------------------------|------------------------------|
| Job definition | JIL `insert_job` attributes (`job_name`, `job_type`, `machine`, `command`, `watch_file`, `condition`, `box_name`, scheduling attrs, logs, alarms) | Topology job definition / config |
| Run instance | `autorep -J job -q` (status, run machine, resolved globals, actual start/end) | Run record / API instance |

The comparison tool normalizes both sides into `NormalizedJob` for migration parity checks.

## Unified ↔ AutoSys JIL

| Unified field | JIL / autorep source | Notes |
|---------------|----------------------|--------|
| `scheduler_job_name` | `job_name` | From `insert_job` |
| `job_type` | `job_type` | `BOX`, `CMD`, `FW`, `FT`, … |
| `box_name` | `box_name` | Child jobs inside a box |
| `machine` | `machine` | Required for CMD/FW; not used for BOX |
| `schedule` | `date_conditions`, `start_times`, `start_mins`, `days_of_week`, `run_calendar`, `timezone`, `run_window` | Mapped to `JobSchedule` (cron-like `expression` + calendar metadata) |
| `command` | `command` or `watch_file` (FW) | May include `$${GLOBAL}` per Global Variables doc |
| `condition` | `condition` | `s(job)` success, `d(job)` done, `e(job)` exit code, `v(var)` value |
| `log_paths` | `std_out_file`, `std_err_file` | Order preserved |
| `actual_start` / `actual_end` | Last run timestamps (autorep / API) | Not in JIL |
| `resolved_command` | Command after global substitution at run time | `run_instance` in samples |
| `resolved_parameters` | Global variable values used for substitution | e.g. `BUSINESS_DATE` |
| `status` | Run status (`SUCCESS`, `FAILURE`, …) | Instance only |
| (extended JIL) | `owner`, `permission`, `group`, `application`, `alarm_if_fail`, `max_run_alarm`, `n_retrys`, `send_notification` | Stored in `attributes` / sample `jil` block; not all compared yet |

## Unified ↔ Process Scheduler

| Unified field | Process Scheduler |
|---------------|-------------------|
| `scheduler_job_name` | Topology-qualified job name |
| `schedule` | Cron `expression`, calendar id, timezone |
| `command` | Command line or .NET entry point (`{BusinessDate}` templates) |
| `condition` | `Finish(...)`, etc. |
| `log_paths` | Configured stdout/stderr paths |
| `resolved_command` / `resolved_parameters` | Resolved template for the business date run |

**Parity comparison** (`app/services/comparison.py`) compares definition fields (`schedule`, `command`, `condition`, `log_paths`, `resolved_command`) with normalized text, and run times with the default 60s threshold. Condition and command syntax differ by platform; schedule and resolved command are aligned in the paired samples for mapped jobs.
