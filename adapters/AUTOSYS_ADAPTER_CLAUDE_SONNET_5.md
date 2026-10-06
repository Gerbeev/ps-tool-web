# Claude Sonnet 5 — AutoSys Adapter Integration Instruction

## Mission

Integrate the provided bank-internal Python AutoSys extraction code into this existing project as a production-quality **real AutoSys scheduler adapter**.

The external Python code already knows how to reach/read the internal AutoSys source. Reuse that working integration. Your task is **not** to redesign the extractor or the comparison engine. Your task is to wrap/adapt the extractor so it produces the project's normalized `TopologySnapshot` contract efficiently and safely.

The finished integration must allow the existing application to:

- select an enabled AutoSys environment from Settings/Compare/Browse;
- capture the requested business day/run state from AutoSys;
- preserve both static AutoSys definition semantics and runtime state;
- build topology containment and real execution dependencies;
- save the result through the existing single-current-snapshot flow;
- compare it against Process Scheduler without source-specific code in the comparison engine;
- browse job details from the captured snapshot;
- export/search/filter using the existing application code.

Do the work end-to-end. Do not stop for approval between steps. Ask a question only if the supplied extractor cannot expose a source fact that is mandatory to construct a valid snapshot and there is no defensible way to mark that fact unsupported.

---

## Source of truth — read before coding

Treat the current repository as authoritative. Read these files before implementation:

- `AGENTS.md`
- `app/models.py`
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
- `config/autosys_compare_parameters.yaml`
- `config/job_naming_rules.yaml`
- `config/autosys_environments.yaml`

Reference source shapes are in:

- `examples/autosys_endpoint/README.md`
- `examples/autosys_endpoint/runtime_user_report.sample.yaml`
- `examples/autosys_endpoint/job_definition.sample.jil`
- `examples/autosys_endpoint/job_definition.parsed.sample.yaml`

Those fixtures describe observed AutoSys semantics. They do **not** define an invented HTTP contract. The supplied real extractor/API DTO is the source contract.

---

## Non-negotiable architecture

The integration boundary must remain:

```text
bank/internal AutoSys
        |
        v
provided Python extractor/client
        |
        v
BankAutoSysAdapter
        |
        v
TopologySnapshot
        |
        +--> Current Snapshot Store
        |
        v
Comparison / Browse / Export
```

Do not put AutoSys-specific transport or DTO logic into:

- `app/services/comparison.py`;
- `app/services/identity.py`;
- routes/templates;
- the current snapshot store.

Do not make the comparison engine import the external extractor.

The adapter is the anti-corruption layer.

### Preserve the extractor

Prefer a thin wrapper around the supplied Python code. Keep its proven:

- authentication mechanism;
- WCF/HTTP/CLI/internal-library transport;
- endpoint paths;
- request DTOs;
- parsing routines;
- retry behavior when already correct.

Do not rewrite working bank connectivity merely to make it look like the current mock adapter.

Use `SchedulerAdapter` directly unless the actual source is an absolute HTTP(S) base URL compatible with `EndpointSchedulerAdapter`. Do **not** force `EndpointSchedulerAdapter` onto a CLI, WCF, host:port, library call, or other non-HTTP transport.

---

## First step: inventory the external extractor

Before modifying project code, inspect the supplied AutoSys Python code and produce an internal mapping in your working notes containing:

1. public entrypoints/functions/classes;
2. required connection/environment inputs;
3. authentication inputs and where they come from;
4. whether calls are sync or async;
5. how business date/run is specified;
6. whether results are paged;
7. whether one bulk call returns all jobs or details require per-job calls;
8. stable native job IDs, if present;
9. static JIL/definition fields;
10. runtime fields;
11. box/parent fields;
12. dependency/condition fields;
13. status enum/codes;
14. timestamps and timezone behavior;
15. source completeness markers/counts;
16. error behavior for auth, timeout, missing run, empty result and partial result.

Do not code source mappings from guesses. Confirm them from the extractor/DTOs.

---

## Target implementation shape

Prefer adding bank-specific modules rather than modifying mocks, for example:

```text
app/adapters/
  bank_autosys.py
  bank_autosys_client.py        # optional thin facade around supplied code
```

The exact split may follow the supplied codebase, but keep the `SchedulerAdapter` implementation small and testable.

Expected adapter:

```python
class BankAutoSysAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.AUTOSYS

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

Register it explicitly in `app/adapters/site.py` with `register_adapter(...)` and add the corresponding internal `connector_profile` to the AutoSys environment configuration used by the bank deployment.

Never implement arbitrary class/module imports controlled by YAML.

---

## Context handling

`ComparisonContext` is the request boundary from the application. Use it rather than inventing parallel UI configuration.

Relevant values:

```text
context.environment_id
context.endpoint_url
context.scheduler
context.as_of.kind
context.as_of.value
context.filters.root_box
context.filters.topology_id
```

Map `as_of` to the extractor's actual business-day/run semantics.

Supported application concepts are:

- `business_date`;
- `run_id`;
- `latest`.

If the extractor supports only a subset, validate explicitly and return a clear adapter error for unsupported request modes. Do not silently reinterpret a run ID as a date or silently substitute “latest”.

The host configured in `config/autosys_environments.yaml` is operator-visible connection configuration. If the supplied extractor resolves connections by environment name instead of host, use the configured environment entry and preserve that extractor behavior; do not manufacture an HTTP URL.

---

## Snapshot requirements

`fetch_topology()` must return **one complete, self-consistent capture** for the requested context.

The current application deliberately keeps only one durable comparison capture. The adapter must not add a second snapshot-history/database layer. Persistence is owned by:

- `app/services/current_snapshot_flow.py`;
- `app/services/current_snapshot.py`.

The adapter should simply fetch a complete source state and return it. On Refresh, the application fetches both schedulers, validates both, and atomically replaces the current pair only after both succeed.

Therefore:

- never return a partial snapshot merely to avoid failing Refresh;
- never persist historical copies inside the adapter;
- never read old adapter-private cache data as if it were the requested source state;
- an endpoint/extractor failure must raise a structured/actionable exception, not return an empty snapshot.

A legitimate zero-job result is valid only when the extractor/source proves the result is complete for the requested scope.

---

## Performance requirement: ~2500+ jobs

The current realistic reference topology contains about 2500 jobs. Design the real adapter for at least this scale without N+1 behavior where avoidable.

Priority order:

1. use one source-side bulk/export call when available;
2. use paginated bulk calls and exhaust every page;
3. use batch detail calls when available;
4. only if the source exposes job detail exclusively one job at a time, use bounded/conservative concurrency compatible with the supplied extractor and internal service limits.

Never use unbounded task/thread creation for thousands of jobs.

Do not fetch the same job detail repeatedly during one capture. Cache per-capture native records in local adapter scope if necessary, then discard them after the snapshot is built.

`fetch_job_detail()` must not cause the application to refetch all 2500 jobs merely to open one detail panel. Prefer a source detail lookup when the current snapshot does not already contain detail. For the current comparison snapshot, the application normally browses the already serialized `SnapshotJob`, so populate all comparison-relevant detail during capture when the source can provide it efficiently.

Record safe retrieval diagnostics in `TopologySnapshot.metadata`, e.g. source/API version, page count and completeness flag. Never store credentials or raw sensitive payloads there.

---

## AutoSys data model mapping

AutoSys has two conceptually separate layers. Preserve them separately.

### 1. Static definition/JIL

Map verified source fields into:

```python
SnapshotJob.autosys.jil: AutoSysJobDefinition
```

High-value fields already supported include:

```text
job_name
job_type
machine
box_name
command
watch_file
condition

date_conditions
start_times
start_mins
days_of_week
run_calendar
exclude_calendar
run_window
must_start_times
must_complete_times
timezone

std_out_file
std_err_file
owner
permission
group
application
description
profile
envvars
priority
resources

success_codes
fail_codes
n_retrys

box_success
box_failure
box_terminator
job_terminator

watch_interval
watch_file_min_size

alarm_if_fail
alarm_if_terminated
min_run_alarm
max_run_alarm
term_run_time
send_notification
notification_id
notification_msg
notification_template
notification_alarm_types
auto_hold
auto_delete
```

`AutoSysJobDefinition` allows extra native fields. Preserve unknown JIL fields instead of silently discarding them.

Do not collapse definition values into runtime fields.

### 2. Runtime/run instance

Map verified runtime fields into:

```python
SnapshotJob.autosys.run: AutoSysRunInstance
```

and the corresponding top-level normalized runtime fields.

At minimum, where the source provides them:

```text
native status -> SnapshotJob.status_raw
native status -> SnapshotJob.status (verified normalization)
actual start  -> SnapshotJob.actual_start + autosys.run.actual_start
actual end    -> SnapshotJob.actual_end   + autosys.run.actual_end
exit code     -> SnapshotJob.exit_code    + autosys.run.exit_code
resolved command/watch path -> autosys.run
```

The project derives execution time from:

```text
actual_end - actual_start
```

Do not fabricate `duration_sec` when start/end are unavailable. `SnapshotJob.exec_time` and execution-time comparison already exist.

All real timestamps should be timezone-aware when the source supplies timezone/offset information. Do not strip offsets merely to make values compare.

---

## Identity and IDs

Keep three concepts distinct:

### `scheduler_job_name`

The exact native AutoSys job name used for human inspection and central identity matching.

### `scheduler_native_id`

The stable native AutoSys ID if the extractor exposes one. Preserve it unchanged.

### `job_uid`

A snapshot-local stable **URL-safe opaque UID** used by tree edges/routes.

Requirements:

- unique within the snapshot;
- deterministic for the same native node within a capture/context;
- URL-safe: do not embed `/`, `?`, `#` or arbitrary path separators;
- do not use mutable display text if a stable native ID exists.

Do not set `logical_id` from guessed source rules. The engine centrally annotates identity using explicit mappings and `config/job_naming_rules.yaml`.

Cross-environment naming rules already preserve the 4-digit business code and job-specific remainder while excluding only the environment token. Do not duplicate that parsing inside the adapter.

---

## Topology containment

AutoSys box membership is structural containment.

Map verified box membership to:

```text
SnapshotJob.parent_uid
```

and preserve native box name in:

```text
SnapshotJob.autosys.jil.box_name
```

Build the tree with `TopologySnapshotBuilder`.

Do **not** convert box membership itself into a `DependencyEdge`.

For a referenced parent box that is inside the requested snapshot, the corresponding `parent_uid` must resolve to an emitted job. Do not leave dangling parent IDs.

If root scoping is requested, follow the existing root/context behavior rather than returning unrelated jobs outside the requested scope.

---

## Execution dependencies

Execution dependency semantics come from real AutoSys conditions/dependency data, not from tree position.

Build `DependencyEdge` only from verified source semantics such as explicit AutoSys conditions.

Rules:

- preserve the original condition expression in the source definition;
- parse only the condition grammar actually supported by the real extractor/source;
- map predecessor references to emitted `job_uid`s;
- preserve dependency kind/condition where representable;
- never infer a dependency because two jobs share a box;
- never infer a dependency from report ordering;
- never drop an unrecognized condition silently.

If an AutoSys condition contains semantics richer than `DependencyEdge` can represent, preserve the source condition and mark the affected comparison capability/field `UNKNOWN` or `UNSUPPORTED` rather than inventing equivalence.

Add sanitized fixtures/tests for every condition form you actually parse.

---

## Status mapping

Do not hard-code a status table from the mock data alone.

Inspect the actual extractor/native enum/code documentation and implement an explicit deterministic mapping to `JobStatus`:

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

Always preserve the exact source code/string in `status_raw`.

Unknown/new source statuses must map to `JobStatus.UNKNOWN` while retaining the raw value. They must never default to success.

Test every status observed in representative source data.

---

## Comparison field support

Real adapters must run in strict capability mode.

Use:

```python
complete_parameter_support(...)
```

and return:

```python
AdapterCapabilities(
    topology=True/False,
    dependencies=True/False,
    runtime=True/False,
    job_detail=True/False,
    root_listing=True/False,
    autosys_projection=True,
    strict_parameter_support=True,
    parameter_support=...,
)
```

Review **every** parameter in `config/autosys_compare_parameters.yaml`.

For each parameter choose exactly one source truth:

- `SUPPORTED` — extractor/source reliably provides it;
- `UNSUPPORTED` — source cannot provide it;
- `UNKNOWN` — semantics/mapping not yet verified;
- `NOT_APPLICABLE` — field has no meaning for that job/type.

Use job-level `comparison_support` for type-specific fields. Example: File Watcher fields are not applicable to ordinary CMD jobs.

Never populate a missing field with `""`, `0`, `False`, or a guessed default merely to make two sides match. Unsupported values must surface as **not comparable**, not false matches or false mismatches.

---

## Field evidence

For non-obvious mappings populate `SnapshotJob.comparison_evidence` with minimal structural provenance.

Example shape:

```python
FieldEvidence(
    source="autosys_extractor",
    locator="<DTO/property/path>",
    note="Mapped from static AutoSys definition",
)
```

Do not include:

- passwords/tokens;
- full commands containing secrets;
- raw log output;
- full endpoint payloads;
- sensitive business data.

Evidence exists to explain mappings, not to mirror source data.

---

## Health check and root listing

`health_check()` must be cheap and read-only. Prefer a purpose-built extractor/client health/status call. If none exists, use the least expensive authenticated metadata operation.

Do not implement health check by downloading all jobs.

`list_roots()` should return real selectable AutoSys roots/boxes if the source supports root discovery. If the external code has no safe root-list operation, return an empty list and declare `root_listing=False` rather than inventing roots.

---

## Error handling

Surface source failures explicitly. Distinguish at least:

- invalid/missing configuration;
- authentication/authorization failure;
- connection/timeout failure;
- source-side error;
- unsupported `as_of` mode;
- requested run/business date not found;
- schema/DTO incompatibility;
- incomplete pagination/truncated result;
- malformed required identity/topology data.

Use bounded retries only for safe idempotent reads and only when the supplied integration/source policy allows them. Respect existing retry logic if the external code already implements it correctly. Avoid retry storms and duplicate retry layers.

Never convert source failure into `TopologySnapshot(flat_jobs=[])`.

---

## Configuration and secrets

Keep operator-editable environment config minimal:

```text
Environment
Host
Description
Enabled
```

The bank deployment may add internal `connector_profile` to select the real adapter. Do not reintroduce redundant UI fields.

Do not put credentials into YAML, source code, URLs or logs. Reuse the authentication mechanism expected by the supplied extractor and bank runtime (environment variables, approved secret store, Windows identity, Kerberos, certificate, etc.).

If the extractor requires new non-secret runtime configuration, make it explicit and document it in `.env.example` or appropriate bank deployment documentation without committing real values.

---

## Security / data handling

This is bank-internal data. Follow these rules:

- never commit real endpoint payloads;
- never commit real commands/log output if they can contain sensitive values;
- never commit tokens/passwords/certificates;
- no raw payload logging by default;
- log structured operational metadata only: request/capture id, environment, operation, outcome, duration, counts;
- sanitize exceptions before displaying/logging if the external library embeds credentials/request bodies;
- keep adapter read-only;
- do not add arbitrary code execution or configuration-driven imports.

Tests/fixtures committed to the repository must be synthetic or sanitized.

---

## Testing strategy

Do not test only the happy-path method return value.

### Unit tests

Create sanitized/fake extractor responses covering:

- complete static definition + runtime mapping;
- BOX/CMD/File Watcher types that the source really supports;
- status mappings;
- timezone-aware timestamps;
- missing optional fields;
- unknown source fields preserved;
- containment;
- explicit dependencies;
- duplicate/missing IDs;
- empty complete result;
- partial/truncated pagination failure;
- source exception propagation;
- unsupported comparison fields;
- URL-safe `job_uid`.

### Contract tests

The adapter must pass:

```bash
python -m app.adapters.check \
  --environment <autosys-environment-id> \
  --scheduler autosys \
  --as-of <YYYY-MM-DD>
```

Use the correct `--as-of-kind` if the real extractor is run-ID based.

### Full regression suite

Run:

```bash
python -m pytest -q
```

Do not weaken existing tests to make the adapter pass.

### Performance smoke

Exercise a sanitized/synthetic dataset of approximately 2500 jobs and verify:

- complete fetch;
- no repeated per-job source calls when bulk data is available;
- snapshot validation passes;
- Browse/job detail works from the snapshot;
- current snapshot serialization/deserialization works;
- Refresh replaces the current capture only after successful complete fetch.

---

## Integration tests against current snapshot flow

Verify these behaviors explicitly:

1. first Compare fetches AutoSys and Process Scheduler and writes a current pair;
2. repeated Compare with identical contexts reuses the stored pair and does not call AutoSys again;
3. `Refresh & compare` calls the AutoSys extractor again;
4. changing business date/run/root makes the current snapshot stale and causes a new capture;
5. an AutoSys fetch failure does not replace the previous valid current pair;
6. Browse of an exact current AutoSys context uses the frozen snapshot.

Do not add history management.

---

## Files normally allowed to change

Prefer changes limited to:

```text
app/adapters/bank_autosys*.py
app/adapters/site.py
config/autosys_environments.yaml          # connector_profile only when needed
.env.example                              # non-secret settings only
tests/...                                 # sanitized/fake extractor tests
docs/...                                  # only integration-specific documentation
```

Modify shared domain/comparison code only if a reproducible real-source case proves the existing model cannot represent required semantics. If that happens:

1. add a failing test demonstrating the gap;
2. make the smallest backward-compatible model extension;
3. keep source-specific logic inside the adapter;
4. rerun all tests.

Do not redesign the application while integrating the connector.

---

## Definition of Done

The AutoSys adapter is complete only when all of the following are true:

- the provided Python extractor is reused rather than unnecessarily rewritten;
- the real adapter is explicitly registered through `app/adapters/site.py`;
- the configured AutoSys environment resolves to the real adapter when `USE_MOCK_ADAPTERS=false`;
- business date/run selection is mapped correctly;
- the adapter proves complete retrieval, including all pages/batches;
- static JIL and runtime state remain separate;
- native fields are preserved where useful;
- `job_uid`s are stable, unique and URL-safe;
- box containment and execution dependencies are not conflated;
- status normalization is explicit and raw status is preserved;
- strict comparison-field coverage is complete;
- unsupported/unknown fields become `not comparable`, not fabricated values;
- snapshot validation has no errors;
- approximately 2500 jobs are handled efficiently;
- the current-snapshot flow works without adapter-private history;
- adapter contract CLI exits `0`;
- full `pytest` suite passes;
- no secrets or real bank payloads are committed.

At completion, report concisely:

1. files changed;
2. external extractor entrypoints reused;
3. mapping decisions made;
4. fields still `UNSUPPORTED`/`UNKNOWN` and why;
5. retrieval/job/dependency counts from a safe test run;
6. contract-test result;
7. full test result;
8. any remaining bank-runtime configuration required.
