# Agent Instructions: Bank-Side Endpoint Adapter Integration

## Objective

Connect this existing comparison engine to the bank-internal AutoSys and Process Scheduler HTTP/API endpoints. Do not redesign the comparison engine unless a reproducible contract test demonstrates that the normalized model cannot represent a required source semantic.

Both schedulers are integration boundaries exposed through endpoints:

- AutoSys adapter -> AutoSys integration endpoint;
- Process Scheduler adapter -> Process Scheduler endpoint.

Process Scheduler may internally read topology/runtime data from Cosmos DB or other storage. That implementation detail is **outside this tool's boundary**. Do not connect this application directly to Cosmos DB and do not parse Process Scheduler persistence formats unless the endpoint contract explicitly returns such data and there is no structured alternative.

## Allowed Integration Surface

Prefer changes only in:

- new `app/adapters/bank_autosys*.py` modules;
- new `app/adapters/bank_process_scheduler*.py` modules;
- `app/adapters/site.py` for explicit adapter registration;
- `config/environments.yaml` for endpoint/profile selection;
- `config/identity_map.yaml` for verified name mappings;
- tests/fixtures containing sanitized or synthetic endpoint payloads.

Do not put source-specific conditions into `app/services/comparison.py`.

## Required Workflow

1. Inspect the real endpoint contracts, DTOs/OpenAPI definitions, and representative sanitized responses inside the bank before coding mappings.
2. Identify stable job IDs, topology/container relations, explicit execution dependencies, schedules, commands, runtime states, timing, logs and equivalent migration fields from the endpoint response models.
3. Implement one `SchedulerAdapter` per endpoint.
4. Use `TopologySnapshotBuilder`; never infer execution dependencies from UI/tree containment.
5. Enable `strict_parameter_support=True` for real adapters and explicitly declare every comparison field with `complete_parameter_support()`.
6. Mark unavailable mappings as `UNSUPPORTED` or `UNKNOWN`; never fabricate empty values to make the contract pass.
7. Mark type-specific irrelevant fields `NOT_APPLICABLE` at job level.
8. Add `comparison_evidence` for non-obvious mappings so mismatches are traceable to endpoint response fields/DTO paths.
9. Register adapters explicitly in `app/adapters/site.py`. Do not implement configuration-controlled arbitrary Python imports.
10. Run adapter contract checks and the full test suite.

## Endpoint Rules

- Treat each endpoint response as the adapter's source of truth.
- Topology/container membership -> `parent_uid` only.
- Explicit dependency/trigger relation -> `DependencyEdge`.
- Native status -> normalized `JobStatus` plus unchanged `status_raw`.
- Native fields semantically equivalent to AutoSys -> `autosys.jil` / `autosys.run` projection.
- Native fields with no safe AutoSys equivalent -> preserve in `attributes` and mark the corresponding comparison field unsupported/not-applicable.
- Do not force every Process Scheduler concept into JIL.
- Do not reconstruct missing dependencies from ordering, nesting, display position, or naming conventions.
- Do not query Process Scheduler's Cosmos DB directly from this tool; the Process Scheduler endpoint owns its storage model.

## AutoSys Rules

- Preserve static definition separately from runtime state.
- Box membership is containment, not an execution dependency by itself.
- Build dependency edges from real conditions/dependency semantics exposed by the AutoSys endpoint.
- Preserve unknown JIL/native attributes returned by the endpoint; do not silently drop source fields.
- Reuse the existing semantic normalization and validation logic instead of raw string comparison.

## Identity Rules

The engine assigns logical identity after retrieval. Prefer verified `identity_map.yaml` mappings where names differ. For cross-environment matching, follow `config/job_naming_rules.yaml`: parse the fixed shared prefix, four-digit business code, environment token, and job-specific remainder; retain business code + job-specific name in the canonical identity and exclude the environment token. Do not hardcode concrete business/environment values into the naming rule. Do not resolve duplicate logical IDs by choosing the first result. Identity conflicts must remain visible until resolved.

## Required Validation Commands

```bash
python -m app.adapters.check --environment <autosys-env> --scheduler autosys --as-of <YYYY-MM-DD>
python -m app.adapters.check --environment <ps-env> --scheduler process_scheduler --as-of <YYYY-MM-DD>
python -m pytest -q
```

All adapter contract checks must exit `0`. The full suite must pass.

## Data and Security Constraints

- Do not copy bank endpoint payloads, job definitions, commands, credentials, hostnames, log content or production data outside the bank environment.
- Do not commit secrets or access tokens. Use approved environment/secret management and the bank's required authentication mechanism.
- Do not log raw endpoint payloads by default.
- Do not put credentials or sensitive data into query parameters when headers/body are supported by the endpoint contract.
- Keep field evidence minimal and structural; never include secrets or sensitive runtime output.
- Any fixtures committed to the repository must be synthetic or sanitized.
- Apply explicit connect/read timeouts and bounded retries in endpoint adapters; do not retry non-idempotent operations. These adapters should normally be read-only.

## Definition of Done

The integration is complete only when:

- both real endpoint adapters pass contract checks;
- strict field coverage has no undeclared parameters;
- containment and dependency semantics have been separately verified against the endpoint DTOs;
- identity conflicts are resolved or explicitly accepted as unresolved;
- unsupported fields appear as `not comparable`, not mismatches;
- known controlled differences produce expected comparison results;
- endpoint failures surface as structured adapter errors rather than partial/empty snapshots;
- no regression is introduced into the engine test suite.
