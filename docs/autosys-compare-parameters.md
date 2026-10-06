# AutoSys reference comparison parameters

Migration parity compares an AutoSys definition/run view with the AutoSys-equivalent projection produced by the Process Scheduler adapter.

The parameter list is configured in `config/autosys_compare_parameters.yaml`.

## Comparison principles

- Definition parity and runtime parity are kept separate.
- Native scheduler status strings are not compared. `SnapshotJob.status` is the normalized cross-scheduler status.
- Equivalent AutoSys syntax is canonicalized before comparison.
- Dependency graph parity is derived from `TopologySnapshot.edges` and appears as the synthetic `dependencies` mismatch parameter.
- Unknown JIL fields are preserved and can be enabled later in configuration.

## High-value definition groups

### Execution and placement

`job_type`, `machine`, `box_name`, `command`, `watch_file`, `profile`, `envvars`, `exit_code_policy`

### Scheduling

`date_conditions`, `start_times`, `start_mins`, `days_of_week`, `run_calendar`, `exclude_calendar`, `run_window`, `must_start_times`, `must_complete_times`, `timezone`

Important rules:

- `days_of_week` and `run_calendar` are alternative run-day mechanisms.
- `start_times` and `start_mins` are mutually exclusive.
- `must_start_times` / `must_complete_times` require an active date schedule and a start-time definition.

### File Watcher

`watch_file`, `watch_interval`, `watch_file_min_size`

### Box / flow control

`box_success`, `box_failure`, `box_terminator`, `job_terminator`, plus dependency graph parity.

### Runtime controls and alarms

`alarm_if_fail`, `alarm_if_terminated`, `min_run_alarm`, `max_run_alarm`, `term_run_time`, `n_retrys`, `send_notification`, `auto_hold`, `auto_delete`

### Output and workload metadata

`std_out_file`, `std_err_file`, `owner`, `permission`, `group`, `application`, `priority`, `resources`

## Runtime comparison

Default runtime fields:

- `resolved_command`
- `exit_code`
- `actual_start`
- `actual_end`

`actual_start` and `actual_end` use `timing_threshold_sec` (60 seconds by default). Completed-job execution time is derived separately as `actual_end - actual_start`; `execution_time_threshold_sec` (300 seconds by default) controls when the signed right-minus-left duration delta is classified as an execution-time mismatch.

## Exit-code policy

`exit_code_policy` is a derived semantic value rather than a literal JIL field:

- `fail:<codes>` when `fail_codes` is configured;
- otherwise `success:<codes>` when `success_codes` is configured;
- otherwise `success:0` (default command-job behavior).

This prevents equivalent explicit/default definitions from being flagged as different.
