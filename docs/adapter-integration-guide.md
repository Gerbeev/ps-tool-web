# Adapter Integration Guide

This repository is intentionally designed so the comparison engine can be developed outside the bank with synthetic data and connected to real AutoSys and Process Scheduler sources later without changing comparison logic.

## Integration Boundary

A real connector must implement `SchedulerAdapter` and return a normalized `TopologySnapshot`.

The engine owns:

- job identity matching;
- semantic AutoSys field normalization;
- definition/runtime comparison;
- topology containment comparison;
- execution dependency comparison;
- partial-coverage handling;
- identity-conflict detection;
- snapshot validation;
- CSV/UI reporting.

The adapter owns only source-system retrieval and source-to-domain mapping.

## Files an Integration Agent Should Touch

The normal bank-side integration should be limited to:

1. one AutoSys adapter module;
2. one Process Scheduler adapter module;
3. `app/adapters/site.py` to register both adapters;
4. `config/environments.yaml` to select the registered `connector_profile`;
5. `config/identity_map.yaml` only when scheduler names cannot be matched deterministically by existing rules.

The agent should not modify `app/services/comparison.py` for source-specific behavior.

## Required Adapter Contract

Implement:

```python
class BankAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.AUTOSYS  # or PROCESS_SCHEDULER

    def capabilities(self) -> AdapterCapabilities: ...
    def health_check(self, environment_id: str) -> bool: ...
    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot: ...
    def fetch_job_detail(self, context: ComparisonContext, job_uid: str) -> SnapshotJob | None: ...
    def list_roots(self, context: ComparisonContext) -> list[str]: ...
```

Use `TopologySnapshotBuilder` to build the tree and dependency list. It deliberately does **not** infer dependencies from topology nesting.

## Strict Capability Declaration

Real adapters should use `strict_parameter_support=True` and explicitly declare support for every comparison field.

Use `complete_parameter_support()` to avoid omissions:

```python
from app.adapters.base import complete_parameter_support
from app.models import AdapterCapabilities, FieldSupport

support = complete_parameter_support(
    overrides={
        "notification_template": FieldSupport.UNSUPPORTED,
        "watch_file_min_size": FieldSupport.NOT_APPLICABLE,
    }
)

capabilities = AdapterCapabilities(
    topology=True,
    dependencies=True,
    runtime=True,
    autosys_projection=True,
    strict_parameter_support=True,
    parameter_support=support,
)
```

Meanings:

- `supported`: the adapter can reliably populate the field;
- `unsupported`: the source/integration cannot provide it;
- `unknown`: mapping is not yet implemented or confidence is insufficient;
- `not_applicable`: the field has no meaning for this job/type.

Unsupported/unknown/not-applicable values are reported as **not comparable**, not as migration mismatches.

Job-level `comparison_support` overrides adapter-level support and should be used for type-specific differences, e.g. File Watcher-only fields.

## Field Provenance

For difficult mappings, populate `SnapshotJob.comparison_evidence` using endpoint DTO field paths:

```python
job.comparison_evidence["command"] = FieldEvidence(
    source="process_scheduler_endpoint",
    locator="topology.nodes[].execution.command",
    note="Mapped from Process Scheduler endpoint DTO",
)
```

The evidence is propagated into mismatch/not-comparable records so an engineer can trace exactly where a normalized value came from.

Do not put secrets, full endpoint payloads, raw PII, credentials, or sensitive command output into evidence strings.

## Process Scheduler Endpoint Mapping

The Process Scheduler integration boundary is its bank-internal endpoint. The scheduler may internally use Cosmos DB or other persistence, but this application must not couple to that storage layer. The adapter maps the endpoint's structured response DTOs into the engine domain model.

Map endpoint concepts as follows:

| Native endpoint concept | Engine field |
|---|---|
| stable job/node ID | `SnapshotJob.job_uid` / `scheduler_native_id` |
| display job name | `scheduler_job_name` |
| topology/container relationship | `parent_uid` |
| explicit predecessor/trigger relation | `DependencyEdge` |
| native execution state | normalized `status` + original `status_raw` |
| native command/assembly invocation | AutoSys-equivalent `autosys.jil.command` when semantically comparable |
| native schedule/calendar | corresponding AutoSys-equivalent scheduling fields |
| runtime command/parameters | `autosys.run.resolved_command` and runtime fields |
| source-specific metadata | `attributes` |

### Critical Rule: Containment Is Not Dependency

A returned topology/container structure such as:

```text
Topology
  JobA
  JobB
  JobC
```

only establishes containment. Do not emit `JobA -> JobB -> JobC` unless the endpoint explicitly exposes execution dependencies/triggers establishing those relations. Never infer them from ordering or nesting.

### Endpoint Completeness

If the Process Scheduler endpoint paginates, the adapter must retrieve all pages before building the snapshot. Authentication failures, timeouts, 5xx responses, incompatible response schemas, or incomplete pagination are adapter failures and must not be represented as an empty topology.

## AutoSys Adapter Mapping

The AutoSys adapter should populate both static definition and runtime information when available:

- `AutoSysJobDefinition` for JIL/definition fields;
- `AutoSysRunInstance` for runtime/autorep-style fields;
- explicit execution dependencies in `snapshot.edges`;
- containment through `parent_uid` for Box membership.

Unknown JIL fields are preserved by the model and can later be added to `config/autosys_compare_parameters.yaml` without changing the domain class.

Do not derive execution dependency solely from Box membership. Parse real AutoSys condition/dependency semantics.

## Stable IDs

`job_uid` must be stable and unique within one snapshot. Prefer a scheduler-native immutable ID. If the source provides no stable ID, construct one deterministically from topology ID + native path + native name.

Do not use only a display name when duplicate names can exist in separate topologies.

## Identity Matching

The engine assigns `logical_id` centrally after retrieval. It uses:

1. explicit mappings in `config/identity_map.yaml`;
2. configured regex rules;
3. normalization rules;
4. name fallback.

If multiple jobs resolve to the same logical ID on one side, the engine reports an `identity_conflict` and excludes them from automatic pairing rather than silently selecting one.

## Validation

Run the adapter contract check before using Compare:

```bash
python -m app.adapters.check \
  --environment uat-rd \
  --scheduler autosys \
  --as-of 2026-10-02
```

For Process Scheduler:

```bash
python -m app.adapters.check \
  --environment test-rd \
  --scheduler process_scheduler \
  --as-of 2026-10-02
```

The command returns non-zero when the normalized snapshot violates the contract.

Validation currently checks:

- duplicate `job_uid`;
- missing/self/cyclic parents;
- dangling/self/duplicate dependencies;
- dependency cycles (warning);
- AutoSys semantic inconsistencies;
- logical identity collisions;
- strict comparison-support completeness;
- adapter capability/output inconsistencies.

## Explicit Registration

Do not load arbitrary Python class paths from YAML/environment variables.

Register trusted adapter factories in `app/adapters/site.py`:

```python
from app.adapters.registry import register_adapter
from app.adapters.bank_autosys import BankAutoSysAdapter
from app.adapters.bank_process_scheduler import BankProcessSchedulerAdapter

register_adapter("bank_autosys", lambda env: BankAutoSysAdapter(env))
register_adapter("bank_process_scheduler", lambda env: BankProcessSchedulerAdapter(env))
```

Then configure those profile names in `config/environments.yaml` and set:

```text
USE_MOCK_ADAPTERS=false
```

## Definition of Done for a Real Adapter

A connector is ready for migration validation when:

- adapter contract check exits with code `0`;
- strict parameter coverage is complete;
- unsupported fields are explicitly declared;
- topology containment and dependency edges are independently verified;
- stable IDs are deterministic;
- identity conflicts are zero or intentionally resolved;
- a known synthetic fixture produces expected mismatches;
- no source secrets/raw payloads are written to logs;
- the complete repository test suite passes.
