# Claude Sonnet 5 — Process Scheduler Adapter Integration Instruction

## Mission

Integrate the provided bank-internal Python Process Scheduler extraction/orchestration code into this existing project as a production-quality **real Process Scheduler adapter**.

Process Scheduler is a custom internal scheduler. The supplied Python code already knows how to communicate with the internal system. Reuse that working code and adapt its output to this project's `SchedulerAdapter` / `TopologySnapshot` contract.

Your task is **not** to reproduce Process Scheduler internals, query its Cosmos DB directly, redesign the extractor, or add Process Scheduler-specific logic to the comparison engine.

The completed adapter must support the existing application flow:

```text
Environment -> Topology/run -> Jobs -> Full job detail
                       |
                       v
                TopologySnapshot
                       |
                       +--> Current Snapshot Store
                       |
                       v
               Browse / Compare / Export
```

The project currently uses Process Scheduler primarily as the migration target compared against an AutoSys reference environment. Preserve source-native data while projecting only verified migration-parity semantics into the shared comparison model.

Do the integration end-to-end without approval pauses. Ask a question only when the provided extractor lacks information that is mandatory for a valid snapshot and cannot safely be represented as unsupported/unknown.

---

## Source of truth — read before coding

Treat the current repository as authoritative. Read these files first:

- `AGENTS.md`
- `app/models.py`
- `app/process_scheduler_reference.py`
- `app/autosys_reference.py`
- `app/adapters/base.py`
- `app/adapters/builder.py`
- `app/adapters/contract.py`
- `app/adapters/check.py`
- `app/adapters/factory.py`
- `app/adapters/registry.py`
- `app/adapters/site.py`
- `app/services/snapshot_validation.py`
- `app/services/current_snapshot_flow.py`
- `app/services/current_snapshot.py`
- `app/services/identity.py`
- `docs/endpoint-adapter-contract.md`
- `docs/adapter-integration-guide.md`
- `docs/comparison-engine-contract.md`
- `docs/current-snapshot.md`
- `docs/job-naming-rules.md`
- `docs/job-field-mapping.md`
- `config/autosys_compare_parameters.yaml`
- `config/job_naming_rules.yaml`
- `config/process_scheduler_environments.yaml`

Reference source shapes are in:

- `examples/process_scheduler_endpoint/README.md`
- `examples/process_scheduler_endpoint/environments.raw.txt`
- `examples/process_scheduler_endpoint/environments.sample.yaml`
- `examples/process_scheduler_endpoint/topologies.U5.raw.txt`
- `examples/process_scheduler_endpoint/topologies.U5.sample.yaml`
- `examples/process_scheduler_endpoint/topology.DataPlatform_20261001_Friday.raw.txt`
- `examples/process_scheduler_endpoint/topology.DataPlatform_20261001_Friday.sample.yaml`
- `examples/process_scheduler_endpoint/job_detail.IB_CT_CVA_1109_U5_Admin_Box.raw.txt`
- `examples/process_scheduler_endpoint/job_detail.IB_CT_CVA_1109_U5_Admin_Box.sample.yaml`

Those fixtures preserve observed source behavior. They are not a license to invent missing DTO fields. The provided real Python extractor and its DTOs are the source contract.

---

## Non-negotiable architecture

Keep the integration boundary:

```text
Process Scheduler internal system
        |
        v
provided Python extractor/client
        |
        v
BankProcessSchedulerAdapter
        |
        v
TopologySnapshot
        |
        +--> Current Snapshot Store
        |
        v
Comparison / Browse / Export
```

Process Scheduler may use Cosmos DB internally. That storage layer is **opaque** to this project.

Do not:

- connect this application directly to Cosmos DB;
- copy C# persistence models into the comparison engine;
- put WCF/transport code in routes or comparison services;
- infer scheduler behavior from database records when the Process Scheduler endpoint/extractor already owns that interpretation.

### Preserve the supplied integration

The Python code may use:

- WCF;
- host:port connections;
- an internal library;
- HTTP(S);
- Windows/Kerberos auth;
- another bank-specific transport.

Keep the working mechanism. Use `SchedulerAdapter` directly unless the real client genuinely exposes an HTTP(S) base URL compatible with `EndpointSchedulerAdapter`.

The current Process Scheduler config intentionally stores operator-facing `host` values, some of which are host:port rather than URL-shaped. Do not prepend a fake HTTP scheme merely to inherit a base class.

---

## First step: inventory the external extractor

Before implementation, inspect the supplied Process Scheduler Python code and capture in working notes:

1. environment-list operation;
2. topology-list operation;
3. topology/run snapshot operation;
4. full job-detail operation;
5. authentication/configuration inputs;
6. sync vs async behavior;
7. paging/batching behavior;
8. source counts/completeness indicators;
9. stable topology ID/revision/run ID;
10. stable job/node IDs;
11. explicit parent/container relations;
12. explicit dependency relations;
13. job type enum;
14. status enum;
15. schedule representation;
16. execution target/machine/context representation;
17. command/.NET invocation representation;
18. timestamps and timezone behavior;
19. condition expression grammar if exposed;
20. error behavior for invalid environment/topology, auth, timeout and partial fetch.

Do not begin parity projection before this inventory is complete.

---

## Observed Process Scheduler source layers

The reference captures establish four separate layers. Preserve this separation in the real integration where the source API has equivalent concepts.

### Layer 1 — environments

Observed logical shape:

```text
CODE
NAME/DESCRIPTION
WCF ADDRESS / HOST
```

Environment configuration is already maintained in:

```text
config/process_scheduler_environments.yaml
```

The Settings UI owns operator edits for:

```text
Environment
Host
Description
Enabled
```

Do not duplicate the environment catalog into a new adapter database.

If the extractor has an environment-discovery operation, use it for health/verification if helpful, but do not silently overwrite operator config during normal fetch.

### Layer 2 — topologies

`list_roots(context)` should map to the real topology/run-list operation where possible.

Return source topology names/identifiers used by the UI. Do not fabricate names from dates.

### Layer 3 — topology snapshot / job list

A selected topology/run returns snapshot metadata plus jobs. The reference indicates potentially thousands of rows, so retrieval completeness matters.

Capture safe metadata such as:

- native topology ID/name;
- revision if meaningful;
- source snapshot timestamp;
- source-reported total job count;
- page count;
- completeness flag;
- source/client version when available.

### Layer 4 — full job detail

The project has a typed native source model:

```python
ProcessSchedulerJobReference
```

Populate it from the real detail DTO wherever fields are provided.

Known observed wire fields are:

```text
Box
ConditionExpression
Context
Description
JobType
LastFinishTime
LastStartTime
Name
Owner
Schedule
StartAtTime
StartAtTimeForce
Status
```

Unknown future source fields are preserved by the model because `extra="allow"`.

Do not discard them prematurely.

---

## Target implementation shape

Prefer bank-specific modules, for example:

```text
app/adapters/
  bank_process_scheduler.py
  bank_process_scheduler_client.py    # optional facade around supplied code
```

Expected adapter:

```python
class BankProcessSchedulerAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.PROCESS_SCHEDULER

    def capabilities(self) -> AdapterCapabilities: ...
    def health_check(self, environment_id: str) -> bool: ...
    def list_roots(self, context: ComparisonContext) -> list[str]: ...
    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot: ...
    def fetch_job_detail(
        self,
        context: ComparisonContext,
        job_uid: str,
    ) -> SnapshotJob | None: ...
```

Register the adapter explicitly in `app/adapters/site.py` using `register_adapter(...)` and add the bank-only `connector_profile` to the appropriate Process Scheduler environment configuration.

Do not implement configuration-driven arbitrary imports.

---

## Context / topology selection

Use `ComparisonContext` as the application request contract:

```text
context.environment_id
context.endpoint_url
context.scheduler
context.as_of.kind
context.as_of.value
context.filters.topology_id
context.filters.root_box
```

Map these fields to the real extractor semantics rather than inventing a parallel run selector.

For a topology/run-based Process Scheduler flow:

- use `context.filters.topology_id` when the UI has selected a topology;
- use `as_of` only where it has a verified source meaning;
- never silently choose an arbitrary topology when multiple candidates exist;
- if a topology is required but absent, return a clear actionable adapter error or use an already-established application default only when that behavior is explicit in the existing project.

Do not infer topology IDs from job names.

---

## Current snapshot semantics

This project intentionally keeps **one current comparison snapshot pair** and no history manager.

Do not add adapter-level historical storage.

The correct lifecycle is:

```text
Compare / Refresh
    |
    +--> fetch complete AutoSys state
    +--> fetch complete Process Scheduler state
    |
    +--> validate both
    |
    +--> atomically publish current pair
```

Your adapter is responsible only for returning a complete `TopologySnapshot` for one requested Process Scheduler context.

Requirements:

- partial topology retrieval must fail the capture;
- source errors must not become an empty snapshot;
- do not mix job rows from one source revision with details from another if the source can change during capture without a consistency mechanism;
- when the extractor exposes snapshot/revision tokens, use them to keep the capture coherent and record them in metadata;
- the adapter itself must not maintain history/revisions beyond what is required during one fetch.

---

## Performance requirement: ~2500+ jobs

The realistic test topology contains about 2500 jobs. The real Process Scheduler adapter must be designed for this scale.

Avoid this pattern:

```text
1 topology list call
+ 2500 sequential detail calls
+ repeated detail calls during Browse
```

Preferred order:

1. one bulk topology snapshot that already includes comparison-relevant fields;
2. bulk/batch detail endpoint if available;
3. paginated bulk detail fetch;
4. only as a last resort, bounded concurrency around per-job detail calls, respecting the existing extractor/service limitations.

Never start thousands of unbounded tasks/threads.

If per-job detail is necessary for comparison fields, fetch each required detail at most once per capture and build the complete `SnapshotJob` before snapshot publication. The durable current snapshot then prevents repeated extraction during normal analysis.

If the list endpoint already provides all comparison-relevant data, do not call the detail endpoint for every job just because it exists. Use full detail lazily only for source-native information not required by comparison, unless the current Browse contract requires that detail to be present offline after capture.

Balance source load against the requirement that Browse/Compare on the frozen current snapshot should not refetch data unnecessarily.

---

## Process Scheduler native preservation

For each job, populate:

```python
SnapshotJob.process_scheduler: ProcessSchedulerJobReference
```

with the native full-detail fields available from the extractor.

This object is source preservation, **not comparison truth**.

Keep the original native status in:

```text
process_scheduler.status
SnapshotJob.status_raw
```

Keep native source-specific fields with no typed property in:

```text
ProcessSchedulerJobReference.model_extra
```

or `SnapshotJob.attributes` where appropriate for non-detail metadata.

Do not force every Process Scheduler concept into AutoSys JIL.

---

## Safe parity projection

The comparison engine currently compares migration parity through normalized runtime fields plus an `AutoSysJobReference` projection.

Only project semantics that are verified from the real source.

### Safe/expected mappings when confirmed by the extractor

| Process Scheduler source | Project target |
|---|---|
| native job name | `scheduler_job_name` |
| stable source job/node ID | `scheduler_native_id` |
| native status | `status_raw` + normalized `status` |
| actual last start | `actual_start` + `autosys.run.actual_start` |
| actual last finish | `actual_end` + `autosys.run.actual_end` |
| exit code, if exposed | `exit_code` + `autosys.run.exit_code` |
| job type | `autosys.jil.job_type` only with verified semantic mapping |
| schedule weekdays/calendar | corresponding JIL-equivalent scheduling fields |
| start-at time | `autosys.jil.start_times` when semantics match |
| owner | `autosys.jil.owner` |
| description | `autosys.jil.description` |
| execution machine/target | `autosys.jil.machine` only when semantically equivalent |
| command/.NET invocation | `autosys.jil.command` / `autosys.run.resolved_command` only when comparable |
| file-watcher target/options | corresponding File Watcher fields when equivalent |

Execution time is already derived centrally from:

```text
actual_end - actual_start
```

Do not add a second duration definition.

### Do not assume equivalence for these observed native fields

Unless the real extractor/source semantics prove otherwise:

```text
Context
StartAtTimeForce
```

remain Process Scheduler-native metadata.

`Box` must not automatically become `parent_uid`/`box_name` solely because one reference example showed a topology name there.

`ConditionExpression` must not automatically become dependency edges until the actual non-null expression grammar/semantics are verified or the extractor exposes explicit parsed dependency objects.

---

## Topology containment

Use only an explicit, verified Process Scheduler parent/container relation for:

```text
SnapshotJob.parent_uid
```

The hierarchy used for Browse must represent actual source containment, not string naming patterns.

Do not infer parenthood from:

- ordering in the job list;
- common job-name prefixes;
- dependency relationships;
- a `Box` field whose semantics have not been verified for nested jobs.

If the extractor exposes topology nodes/children, use those IDs directly and map them to URL-safe `job_uid`s.

A parent referenced inside the snapshot must be emitted as a job/node. No dangling `parent_uid`s.

---

## Execution dependencies

Containment and dependencies are different dimensions.

Build `DependencyEdge` only from explicit scheduler dependency semantics:

- source predecessor/successor records;
- parsed dependency objects exposed by the supplied extractor;
- a verified `ConditionExpression` grammar;
- other documented trigger/dependency relationships.

Do not infer dependencies from tree parenthood or list order.

If `ConditionExpression` is non-null in real data:

1. collect representative sanitized expression forms;
2. identify grammar/operators/status predicates;
3. add parser tests first;
4. build edges only for constructs that can be mapped safely;
5. preserve the original native expression;
6. mark unsupported richer semantics as `UNKNOWN`/`UNSUPPORTED` instead of flattening them incorrectly.

If the source does not expose dependencies at all, declare `dependencies=False` and mark the comparison field unsupported rather than emitting zero edges as if “no dependencies” were known.

---

## Status mapping

The reference UI has shown several native states, but the real mapping must come from the actual extractor/source enum and semantics.

Map deterministically into:

```text
pending
running
success
failure
killed
unknown
not_run
disabled
```

Always preserve the native string/code in `status_raw` and in `ProcessSchedulerJobReference.status` when present.

Never default an unknown state to success.

If semantically different native states collapse into one normalized state, retain the raw state so the UI/evidence can explain the difference.

Add tests for every status observed in sanitized real responses.

---

## Identity and IDs

Keep separate:

### `scheduler_job_name`

Exact Process Scheduler job name.

### `scheduler_native_id`

Stable native ID from Process Scheduler when available.

### `job_uid`

URL-safe opaque UID used internally by the snapshot/tree/routes.

Requirements:

- unique within the snapshot;
- deterministic for the source node;
- no `/`, `?`, `#` or unescaped path structure;
- prefer stable native ID as the input to UID generation.

Do not calculate cross-environment `logical_id` inside the adapter.

Central identity logic already knows how to parse the generic job naming convention:

```text
common prefix + 4-digit business code + environment token + job-specific remainder
```

and compare using:

```text
business code + job-specific remainder
```

while excluding only the environment token.

Let `app/services/identity.py` own this behavior.

---

## Comparison-field support

Use strict adapter capability declaration.

Start from:

```python
complete_parameter_support(...)
```

and review every comparison parameter in `config/autosys_compare_parameters.yaml`.

Set:

```python
AdapterCapabilities(
    topology=...,
    dependencies=...,
    runtime=...,
    job_detail=...,
    root_listing=...,
    autosys_projection=...,
    strict_parameter_support=True,
    parameter_support=...,
)
```

For each comparison field choose:

- `SUPPORTED` — semantically verified source mapping;
- `UNSUPPORTED` — Process Scheduler/extractor cannot provide it;
- `UNKNOWN` — source field exists but equivalence is not verified;
- `NOT_APPLICABLE` — not meaningful for a specific job/type.

Job-level `comparison_support` should override adapter-wide capability where necessary.

Examples:

- file watcher parameters may be `NOT_APPLICABLE` for a box or .NET command job;
- AutoSys-specific alarm/notification semantics may be `UNSUPPORTED` if Process Scheduler has no equivalent;
- an ambiguous source scheduling flag should be `UNKNOWN`, not forced into `date_conditions`.

Never fill missing values with defaults merely to avoid mismatches.

---

## Field evidence

For non-obvious parity mappings populate `comparison_evidence`.

Use structural source locators, e.g. extractor DTO/property names, not storage implementation details.

Example:

```python
FieldEvidence(
    source="process_scheduler_extractor",
    locator="JobDetail.StartAtTime",
    note="Projected to AutoSys-equivalent start_times",
)
```

Do not include secrets, entire payloads, sensitive command arguments or log text.

---

## `list_roots()`

Implement `list_roots(context)` from the real topology-list operation.

Requirements:

- return the complete topology list for the selected environment/scope;
- do not hard-code captured example names;
- preserve source names exactly for selection;
- bounded/cheap call suitable for UI use;
- distinguish source failure from a legitimate empty topology list.

If topology listing is not supported by the supplied extractor, set `root_listing=False` and return `[]` instead of fabricating entries.

---

## `fetch_topology()` recommended sequence

Use the real extractor's capabilities, but the logical sequence should be:

```text
1. validate environment/context
2. resolve selected topology/run
3. capture topology metadata/revision token
4. fetch complete job/node list
5. fetch required full details efficiently
6. map native records to SnapshotJob
7. map explicit containment
8. map explicit dependencies
9. build with TopologySnapshotBuilder
10. validate counts/completeness metadata
11. return complete snapshot
```

If the source exposes a revision/snapshot token, keep all detail requests pinned to it where possible. Do not knowingly combine different live revisions in one snapshot.

---

## `fetch_job_detail()`

When the current frozen snapshot already contains the native detail needed by Browse, the application should use that snapshot rather than source-fetching again.

Still implement `fetch_job_detail()` correctly for standalone Browse/adapter contract use:

- resolve `job_uid` to the corresponding source/native ID safely;
- prefer one targeted source detail call;
- do not rebuild/refetch the entire 2500-job topology for one job;
- map the result using the same mapping function used by `fetch_topology()` so detail semantics cannot drift.

Maintain a clear mapping between opaque `job_uid` and native ID during the active request/snapshot; do not attempt to reverse arbitrary encoded data insecurely if a direct index is available.

---

## Completeness / pagination

The reference UI demonstrates that a topology may contain thousands of jobs while only one page is visible.

The real adapter must prove complete retrieval.

If the source reports total rows/count:

```text
retrieved_count == reported_total
```

must hold unless the API contract explicitly explains excluded rows.

Exhaust all pages/batches. A partial first page must never become a valid snapshot.

Record safe metadata such as:

```python
{
    "source": "process_scheduler_extractor",
    "topology": "...",
    "revision": "...",
    "reported_job_count": 2500,
    "retrieved_job_count": 2500,
    "pages": 125,
    "complete": True,
}
```

Do not put credentials or raw payloads in metadata.

---

## Error handling

Differentiate at least:

- unknown/disabled environment;
- missing host/config;
- authentication/authorization failure;
- connection/timeout failure;
- unavailable Process Scheduler service;
- missing topology/run;
- unsupported as-of mode;
- source revision changed in a way that invalidates capture consistency;
- DTO/schema incompatibility;
- incomplete pagination/detail retrieval;
- missing required job identity;
- malformed parent/dependency references.

A source failure must raise an adapter error and preserve the previous current snapshot. It must not produce an apparently successful empty/partial snapshot.

Use bounded retries only for idempotent reads and only where safe. Do not stack a second retry loop on top of a supplied client that already retries appropriately.

---

## Configuration and secrets

Keep the Settings/config model minimal:

```text
Environment
Host
Description
Enabled
```

Use internal `connector_profile` only for adapter selection; it should not reappear as a normal operator UI field.

Do not store credentials in Process Scheduler YAML.

Reuse the provided extractor's approved auth path. Any new non-secret options should be documented without real bank values.

---

## Security / data handling

- do not commit real Process Scheduler payloads;
- do not commit credentials, tokens, certificates or connection secrets;
- do not log full native job details by default;
- do not log commands/parameters that may contain secrets;
- keep the adapter read-only;
- do not introduce direct Cosmos DB access;
- sanitize external-library exceptions if they include request bodies/credentials;
- use structured operational logs with environment, topology, operation, count, duration and outcome only;
- use sanitized/synthetic fixtures in repository tests.

---

## Testing strategy

### Unit tests

Use fake/sanitized extractor responses to cover:

- environment/topology discovery;
- complete topology retrieval;
- paging/batch completion;
- full detail preservation in `ProcessSchedulerJobReference`;
- unknown detail fields preserved;
- status mapping;
- timezone-aware start/end mapping;
- execution time derived from start/end;
- verified schedule/start-time projection;
- owner/description projection;
- explicit hierarchy;
- explicit dependencies;
- missing/unknown dependency semantics;
- duplicate IDs;
- invalid parent IDs;
- URL-safe `job_uid`;
- partial result failure;
- source exception propagation;
- strict `FieldSupport` behavior.

### Contract CLI

Run:

```bash
python -m app.adapters.check \
  --environment <process-scheduler-environment-id> \
  --scheduler process_scheduler \
  --as-of <appropriate-value>
```

Use the correct `--as-of-kind` for the actual Process Scheduler run/topology contract.

### Full regression

Run:

```bash
python -m pytest -q
```

Do not weaken existing comparison/validation tests.

### Scale smoke

Test a sanitized/synthetic topology around 2500 jobs and verify:

- all jobs are retrieved;
- all explicit dependencies are retrieved;
- detail retrieval is not sequential N+1 when a better source operation exists;
- snapshot validation passes;
- Browse can open root, nested box and leaf job details;
- current snapshot round-trip preserves native Process Scheduler detail;
- Compare can run entirely from the captured snapshot after fetch.

---

## Current snapshot integration tests

Verify:

1. first Compare captures Process Scheduler together with AutoSys;
2. identical repeated Compare does not call Process Scheduler again;
3. `Refresh & compare` performs a fresh Process Scheduler fetch;
4. changing environment/topology/run makes the stored pair stale;
5. Process Scheduler failure after the AutoSys side succeeds does **not** replace the previous valid pair;
6. Browse of an exact current Process Scheduler context uses the durable frozen snapshot;
7. restart-like deserialization preserves tree structure, native detail and dependency edges.

Do not add snapshot history management.

---

## Files normally allowed to change

Prefer changes limited to:

```text
app/adapters/bank_process_scheduler*.py
app/adapters/site.py
config/process_scheduler_environments.yaml   # connector_profile only when needed
.env.example                                 # non-secret options only
tests/...                                    # sanitized/fake extractor tests
docs/...                                     # integration-specific documentation only
```

Modify `ProcessSchedulerJobReference` or another shared model only if actual source DTOs contain important semantics that cannot be preserved by the current typed model + `extra="allow"`/`attributes`.

If a shared model change is truly needed:

1. first add a failing sanitized test demonstrating the real gap;
2. make the smallest backward-compatible extension;
3. keep source-specific interpretation in the adapter;
4. rerun the complete suite.

Do not modify comparison logic merely because the source field names differ.

---

## Definition of Done

The Process Scheduler adapter is complete only when:

- the provided working Python extractor/client is reused;
- no direct Cosmos DB dependency has been added;
- the adapter is explicitly registered in `app/adapters/site.py`;
- enabled Process Scheduler environments select the real adapter with `USE_MOCK_ADAPTERS=false`;
- topology discovery is real and complete when supported;
- the selected topology/run is fetched completely, not only first-page rows;
- full native detail is preserved in `ProcessSchedulerJobReference` where available;
- only verified semantics are projected into AutoSys-equivalent fields;
- `Context`, `StartAtTimeForce`, `Box`, `ConditionExpression` and other ambiguous fields are not force-mapped without evidence;
- `job_uid`s are stable, unique and URL-safe;
- containment and dependencies are independently sourced;
- status normalization is explicit while raw status remains visible;
- strict comparison-field coverage is complete;
- unavailable semantics become `not comparable` rather than fabricated mismatches/matches;
- approximately 2500 jobs are handled efficiently;
- snapshot validation has no errors;
- current-snapshot refresh/reuse/failure behavior remains correct;
- adapter contract CLI exits `0`;
- full `pytest` suite passes;
- no real bank secrets or payloads are committed.

At completion, report concisely:

1. files changed;
2. extractor entrypoints reused;
3. transport/auth mechanism preserved;
4. topology/job/detail retrieval strategy;
5. source-to-domain mapping decisions;
6. fields marked `UNSUPPORTED`/`UNKNOWN` and why;
7. safe job/dependency counts from a test run;
8. contract-test result;
9. full test result;
10. remaining bank-runtime configuration, if any.
