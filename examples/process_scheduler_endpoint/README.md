# Process Scheduler endpoint reference examples

These fixtures are a literal transcription of the provided `ps-tool Browse v1.0.0` screenshots and are intended to drive the future Process Scheduler adapter design.

The observed browse flow is deliberately preserved as four separate layers:

1. `environments` — environment catalogue (`CODE`, `NAME`, `WCF ADDRESS`).
2. `topologies` — topology names for the selected environment (`U5` in the captured example).
3. `topology snapshot / jobs` — revision, snapshot time, status summary and the visible job rows for one selected topology.
4. `full job detail` — the selected job summary plus every raw wire field shown as returned by the server.

No normalized application DTO is invented here. The files preserve the source tool terminology and values so the real endpoint contract can later be mapped to the existing adapter/domain model without losing source semantics.

Files:

- `environments.raw.txt` — source-shaped terminal transcription.
- `environments.sample.yaml` — the same 14 environments, preserving display order and values.
- `topologies.U5.raw.txt` — source-shaped topology list for U5.
- `topologies.U5.sample.yaml` — the same topology list as structured data.
- `topology.DataPlatform_20261001_Friday.raw.txt` — source-shaped snapshot metadata, status summary and first visible page of rows.
- `topology.DataPlatform_20261001_Friday.sample.yaml` — structured representation of the same snapshot/page.
- `job_detail.IB_CT_CVA_1109_U5_Admin_Box.raw.txt` — literal full-detail terminal transcription for the captured box job.
- `job_detail.IB_CT_CVA_1109_U5_Admin_Box.sample.yaml` — structured representation of the same summary and 13 raw wire fields.

Notes:

- The terminal shows `15/15 lines` for the environment catalogue: one header plus 14 environment rows.
- The topology screen shows `6/6 lines`: one header plus 5 topology rows.
- The selected topology page shows `20/2371 lines`: one header plus 19 visible job rows, implying 2370 total job rows. The status-summary counts also sum to 2370.
- Only the visible first page is transcribed. No unseen jobs are fabricated.
- `-` is retained as the source tool's missing/not-present display value in the raw files. Structured YAML uses `null` for those cells and preserves `source_missing_value: "-"`.

## Observed full-detail fields

The captured Process Scheduler job-detail response exposes these source fields: `Box`, `ConditionExpression`, `Context`, `Description`, `JobType`, `LastFinishTime`, `LastStartTime`, `Name`, `Owner`, `Schedule`, `StartAtTime`, `StartAtTimeForce`, and `Status`.

The project now preserves them in the typed `ProcessSchedulerJobReference`. Safe parity projections are intentionally conservative:

- `Name` -> `scheduler_job_name`;
- `Status` -> `status_raw` plus normalized `status`;
- `LastStartTime` / `LastFinishTime` -> runtime timestamps;
- `JobType` -> AutoSys-equivalent `job_type` only when a semantic mapping is known;
- `Schedule` -> `days_of_week`;
- `StartAtTime` -> `start_times`;
- `Owner` / `Description` -> equivalent metadata fields;
- `Box` is preserved natively and may contribute to topology containment only after its endpoint semantics are verified on nested jobs;
- `ConditionExpression` is preserved natively and should become dependency edges only when a non-null real example confirms the expression grammar;
- `Context` and `StartAtTimeForce` remain Process Scheduler-native until a defensible AutoSys equivalent is established.
