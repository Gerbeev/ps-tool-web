# Process Scheduler Endpoint -> AutoSys Migration-Parity Mapping

Process Scheduler is a custom .NET/C# scheduler exposed to this tool through a bank-internal endpoint. The endpoint is the source contract for the adapter. Its internal Cosmos DB/storage representation is intentionally opaque to `ps-tool-web`.

The adapter must map endpoint DTOs into the shared scheduler model and separately build an AutoSys-equivalent parity projection where semantics are genuinely comparable.

## Core Mapping

| Process Scheduler endpoint concept | Engine field |
|---|---|
| stable job/node ID | `SnapshotJob.job_uid` / `scheduler_native_id` |
| display/business job name | `scheduler_job_name` |
| topology/container parent | `parent_uid` |
| explicit predecessor/trigger relation | `DependencyEdge` |
| native execution state | normalized `status` + original `status_raw` |
| native command/.NET invocation | `autosys.jil.command` when semantically comparable |
| native schedule/calendar | corresponding AutoSys-equivalent scheduling fields |
| runtime command/parameters | `autosys.run.resolved_command` and runtime fields |
| source-specific endpoint metadata | `attributes` |


## Observed Process Scheduler job-detail DTO

A captured full-detail response confirms the following wire fields. The adapter should preserve the complete source object in `SnapshotJob.process_scheduler` before projecting safe equivalents.

| Process Scheduler wire field | Normalized/parity handling |
|---|---|
| `Name` | `scheduler_job_name` |
| `Status` | normalized `status` + unchanged `status_raw` |
| `LastStartTime` | `actual_start` / `autosys.run.actual_start` |
| `LastFinishTime` | `actual_end` / `autosys.run.actual_end` |
| derived `LastFinishTime - LastStartTime` | `SnapshotJob.exec_time` (`HH:MM:SS`) and execution-time comparison delta |
| `JobType` | `autosys.jil.job_type` only through verified type mapping |
| `Schedule` | `autosys.jil.days_of_week` when the value is a weekday schedule |
| `StartAtTime` | `autosys.jil.start_times` when it represents the scheduled start time |
| `Owner` | `autosys.jil.owner` |
| `Description` | `autosys.jil.description` |
| `Box` | preserve natively; map to containment/`box_name` only after endpoint semantics are verified for nested jobs |
| `ConditionExpression` | preserve natively; parse into `DependencyEdge` only after real non-null grammar is verified |
| `Context` | Process Scheduler-native metadata; no assumed AutoSys equivalent |
| `StartAtTimeForce` | Process Scheduler-native scheduling flag; no assumed AutoSys equivalent yet |

The distinction between `Box` and `Context` is important: the captured box job has both values equal to the topology name, but one example is not enough to prove that `Box` always means immediate parent containment. Do not derive hierarchy or dependencies from this field until nested-job examples confirm the contract.

## Dependency Mapping

Dependency mapping is mandatory when the Process Scheduler endpoint exposes dependency semantics.

Do not infer a dependency merely because nodes are returned in a particular order or because one job is nested inside the same topology/container as another. Structural containment and execution prerequisites are separate concepts.

If the endpoint exposes richer dependency semantics than `DependencyEdge` can safely represent, preserve the native form in `attributes`, project any equivalent AutoSys condition where valid, and mark unsupported portions as `UNKNOWN`/`UNSUPPORTED` rather than inventing equivalence.

## AutoSys-Equivalent Projection

For Process Scheduler jobs, populate only fields that can be defended semantically against AutoSys. Typical candidates include:

- command / executable invocation;
- machine/target execution context if comparable;
- parent/topology membership;
- schedule/calendar/time-window semantics;
- retry/timeout semantics;
- file-watcher semantics;
- runtime status, start/end timestamps, derived execution time and exit code;
- explicit predecessor dependencies.

A Process Scheduler-native field with no AutoSys equivalent belongs in `attributes`; it should not be forced into an unrelated JIL field.

## Evidence

For non-obvious mappings, use endpoint DTO paths/field names rather than storage locations:

```python
FieldEvidence(
    source="process_scheduler_endpoint",
    locator="topology.nodes[].execution.command",
    note="Mapped from endpoint execution DTO",
)
```

Do not include full endpoint payloads, secrets, commands containing credentials, or sensitive log content.

## Identity

Logical job pairing remains controlled centrally by `config/identity_map.yaml`, `config/job_naming_rules.yaml`, and conservative normalization rules. The naming rule separates the fixed shared prefix, four-digit business code, environment token, and job-specific remainder so the environment token can be removed safely for cross-environment identity while the business code is retained. Native endpoint IDs should be retained as `scheduler_native_id`; they should not replace verified cross-scheduler business identity unless the same stable ID is genuinely shared across both systems.
