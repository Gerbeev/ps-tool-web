# Job field mapping: AutoSys ↔ Process Scheduler

Unified model: `NormalizedJob` in `app/models.py`.

| Unified field | AutoSys (CA WA) | Process Scheduler (in-house) |
|---------------|-----------------|------------------------------|
| `scheduler_job_name` | `job_name` | Topology-qualified job name |
| `schedule` | `run_calendar`, `start_times`, `days_of_week`, `run_window` | Cron / calendar id on job definition |
| `command` | `command` (definition; may include `%%$VAR%%`) | Command line or .NET entry point |
| `condition` | `condition` (`s(job)`, `d(job)`, …) | Dependency expression (`Finish(...)`, etc.) |
| `log_paths` | `std_out_file`, `std_err_file`, agent log paths | Configured log file list |
| `actual_start` / `actual_end` | Last run start/end from `autorep` / API | Run instance timestamps |
| `resolved_command` | Command after global variable substitution for the run | Resolved template after `{BusinessDate}` etc. |
| `resolved_parameters` | e.g. `DATE`, `%%$VAR%%` values | Named parameters used for resolution |
| `status` | `status` (SUCCESS, FAILURE, …) | Run status enum |

**Parity comparison** (see `app/services/comparison.py`) compares definition fields (`schedule`, `command`, `condition`, `log_paths`, `resolved_command`) with normalized text, and run times with the existing timing threshold (default 60s). Condition syntax differs by platform; migrated jobs should be mapped to equivalent expressions before expecting a match.

Sample payloads: `examples/autosys_jobs.sample.yaml`, `examples/process_scheduler_jobs.sample.yaml`.
