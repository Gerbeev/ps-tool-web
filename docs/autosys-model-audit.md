# AutoSys model audit and comparison design

## Scope

This audit validates the application's AutoSys parity model against Broadcom documentation and current Broadcom Knowledge Base material for AutoSys 12.x / 24.x behavior.

The application does **not** attempt to model every agent-specific AutoSys job type. The production comparison target for this project is the high-value migration surface used by Risk Analytics: boxes/topologies, command jobs (including .NET executables launched as commands), File Watcher jobs, schedules, dependencies, runtime controls, and run-instance data.

Unknown JIL attributes are preserved by the model instead of being silently discarded. This allows additional attributes to be enabled in `config/autosys_compare_parameters.yaml` when a real estate contains other AutoSys job types.

## Broadcom references used

- CA Workload Automation AE 11.3.6 User Guide (Broadcom/CA public documentation): common job attributes, starting conditions, look-back dependencies, box semantics, and File Watcher semantics.
  - https://ftpdocs.broadcom.com/cadocs/0/CA%20Workload%20Automation%20AE%20Release%2011%203%206%20-%20Public%20Access-ENU/Bookshelf_Files/PDF/WA_AE_User_ENU.pdf
- AutoSys scheduling attributes (Broadcom KB 395980): `days_of_week`, `exclude_calendar`, `must_complete_times`, `must_start_times`, `run_calendar`, `run_window`, `start_mins`, `start_times`, `timezone`.
  - https://knowledge.broadcom.com/external/article/395980
- AutoSys exit-code policy (Broadcom KB 408778 / 196875): `fail_codes` versus `success_codes` precedence and default exit-code behavior.
  - https://knowledge.broadcom.com/external/article/408778
  - https://knowledge.broadcom.com/external/article/196875
- AutoSys File Watcher behavior (Broadcom KB 445022, AutoSys 12.x / 24.1) and User Guide: `watch_file`, `watch_interval`, `watch_file_min_size`.
  - https://knowledge.broadcom.com/external/article/445022
- Box completion semantics (Broadcom KB 390501 / 446324): `box_success` and default box completion behavior.
  - https://knowledge.broadcom.com/external/article/390501
  - https://knowledge.broadcom.com/external/article/446324
- Box termination behavior (Broadcom KB 94229): `box_terminator`.
  - https://knowledge.broadcom.com/external/article/94229
- Must-start/must-complete constraints (Broadcom KB 40131).
  - https://knowledge.broadcom.com/external/article/40131
- AutoSys 12.x job type codes (Broadcom KB 243720).
  - https://knowledge.broadcom.com/external/article/243720

## Findings from the previous model

### 1. The JIL surface was too small

The previous model covered basic CMD/FW/BOX fields but omitted behavior-changing attributes such as:

- `exclude_calendar`
- `run_window`
- `must_start_times`
- `must_complete_times`
- `success_codes` / `fail_codes`
- `box_success` / `box_failure`
- `box_terminator` / `job_terminator`
- `watch_interval` / `watch_file_min_size`
- `alarm_if_terminated`
- `min_run_alarm`
- `term_run_time`
- `profile` / `envvars`
- `priority` / `resources`
- `auto_hold` / `auto_delete`

These fields can materially change when a job starts, how it completes, whether a box completes, and how a migration behaves at runtime.

### 2. Unknown JIL attributes were silently dropped

`AutoSysJobDefinition.from_mapping()` previously filtered all input to a fixed field list. This is unsafe for a real AutoSys estate because agent-specific or newly introduced attributes disappear before comparison.

The model now preserves unknown attributes and allows them to be opted into comparison configuration later.

### 3. Comparison used raw string equality

Raw equality creates false migration defects for equivalent AutoSys syntax. The comparison now canonicalizes high-value semantics:

- `C` and `CMD`, `B` and `BOX`, `F` and `FW`
- `y`, `1`, `true` (and false equivalents)
- `success(JOB)` and `s(JOB)`
- `AND` and `&`, `OR` and `|`
- reordered `start_times`, `start_mins`, and exit-code lists
- day-of-week aliases

It deliberately does not implement a full JIL parser. Complex boolean expressions remain visible as definition data and should also be represented by structured dependency edges where possible.

### 4. Exit-code semantics were missing

For command jobs, comparing `success_codes` and `fail_codes` independently is not sufficient because their meaning is a policy. The model now compares the derived `exit_code_policy`:

- explicit `fail_codes` -> those codes fail; other codes succeed;
- otherwise explicit `success_codes` -> only those codes succeed;
- otherwise -> default success code `0`.

This avoids false differences such as omitted `success_codes` versus explicit `success_codes: 0`.

### 5. Sample JIL contained invalid scheduling combinations

The previous sample definitions set both `days_of_week` and `run_calendar`. These are alternative run-day mechanisms, not additive fields. The samples now use one or the other.

The model also validates the other important mutual exclusion: `start_times` versus `start_mins`.

### 6. Containment and dependency were mixed

A Box/Topology membership relationship is not the same as an execution dependency.

The domain model now follows this contract:

- `parent_uid` / `JobNode.children`: hierarchy and containment;
- `DependencyEdge`: actual execution dependency only.

Comparison now derives predecessor signatures from `DependencyEdge` and reports a `dependencies` parameter mismatch when a matched job has different upstream dependencies.

This matters for Process Scheduler because dependency information returned by its endpoint must be mapped explicitly rather than reconstructed from display hierarchy.

### 7. Raw scheduler status should not be compared across products

AutoSys and Process Scheduler use different native status vocabularies. The normalized `SnapshotJob.status` remains the cross-scheduler comparison field; `status_raw` and `AutoSysRunInstance.status` remain diagnostic/native values.

The raw run status was removed from the default parameter comparison to avoid false mismatches such as `SUCCESS` versus `Completed`.

### 8. Timing mismatch counting was ambiguous

The previous summary could count both `actual_start` and `actual_end` as two timing mismatches for one job. `mismatched_timing` now counts affected job pairs. The threshold check uses the maximum available start/end delta for a pair.


### 9. `auto_delete` and `send_notification` are not booleans

A second semantic pass found two attributes that must not be normalized as simple true/false flags:

- `auto_delete` is a completion-time deletion delay in hours. `auto_delete: 24` means delete after 24 hours, while `auto_delete: 0` is an explicit immediate-delete behavior; omission is therefore not equivalent to zero.
- `send_notification` is a mode. Broadcom documents `0` as disabled, `1`/`y` as notification for relevant terminal statuses, and `2`/`f` as failure-only behavior. Treating `f` as generic false loses real behavior.

The canonicalizer now preserves these semantics. Notification ID/message/template/alarm types are also part of the parity surface, and `notification_template` plus `notification_msg` is validated as an invalid mutually-exclusive combination.

## Process Scheduler endpoint mapping contract

Process Scheduler is a custom .NET/C# scheduler exposed to this application through a bank-internal endpoint. Its internal Cosmos DB/storage implementation is outside the comparison boundary.

The real Process Scheduler adapter should map the endpoint response into two views:

1. Native topology view
   - endpoint job/node ID -> `scheduler_native_id`
   - node name -> `scheduler_job_name`
   - topology/container membership -> `parent_uid` / `JobNode`
   - explicit dependency links -> `DependencyEdge`
   - native schedule/command/status/log fields -> `SnapshotJob.attributes` and runtime fields

2. AutoSys parity projection
   - only fields that have an AutoSys-equivalent migration meaning are projected into `SnapshotJob.autosys.jil` / `.run`;
   - this projection is the contract used for attribute-level migration comparison;
   - native Process Scheduler values remain available separately and are not destroyed by the projection.

### Dependency rule

Do not create an execution edge merely because two nodes share a topology/container or are returned in a particular order. Create `DependencyEdge` only from explicit dependency/trigger semantics exposed by the endpoint.

## Remaining integration step

The comparison core is ready for structured Process Scheduler endpoint data. The bank-side coding agent only needs the actual endpoint contract/DTOs (or OpenAPI/schema available internally) and representative sanitized responses to implement the adapter. No Cosmos DB schema or XML persistence format is required by this application.
