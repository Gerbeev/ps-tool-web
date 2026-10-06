# AutoSys endpoint source examples

These fixtures capture the AutoSys source shapes visible in the supplied reference screenshots. They are intentionally kept **source-oriented** so the future bank-side endpoint adapter can map the real endpoint DTO into the comparison engine without losing AutoSys semantics.

The screenshots show two distinct data layers that must stay separate:

1. **Runtime/user report** — one row per job with last start/end, native state code, run/try information, priority/exit column and timezone.
2. **Static JIL definition** — job type, box membership, command, machine, owner, permissions, conditions, logs, alarms, profile, timezone, group and application.

Files:

- `runtime_user_report.sample.yaml` — representative parsed rows from the AutoSys self-help user report.
- `job_definition.sample.jil` — raw JIL text for `IB_CT_CVA_1109_U1_DP_ADP_Accounts_Load`, with screenshot line wrapping normalized only where the command wrapped visually.
- `job_definition.parsed.sample.yaml` — structured parse of the same JIL plus the matching runtime row from the report.

## Important contract notes

- This folder is **not** an invented HTTP/JSON contract. The real AutoSys endpoint DTO is still unknown and must be mapped later from its actual schema.
- Native values are preserved. In particular, `ST/Ex`, `Run/Ntry`, and `Pri/Xit` are stored as raw values because their exact endpoint field split/semantics must be confirmed against the real API contract.
- `box_name` is structural containment. It must not be converted into an execution dependency.
- The JIL `condition` is execution/dependency semantics and should later be parsed into dependency edges where safe.
- Static definition and runtime state must not be collapsed into one source object inside the adapter.
- The report contains native status codes such as `SU`, `RU`, `IN`, `OI`, and `AC`; their normalized `JobStatus` mapping should be confirmed against the endpoint/AutoSys documentation before hard-coding it.
