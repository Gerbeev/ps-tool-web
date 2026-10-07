# Workstation Integration Guide

The supported real-integration path is `scheduler-bridge/v1`. Do **not** implement bank-specific `SchedulerAdapter` subclasses inside the portable web project.

## One-time workstation setup

1. Copy `examples/workstation_connectors/bridge_v1_runtime.py` to `workstation_connectors/`.
2. Copy `examples/workstation_connectors/autosys_connector.py` to `workstation_connectors/`.
3. Copy `examples/workstation_connectors/process_scheduler_connector.py` to `workstation_connectors/`.
4. Wire the two provider files to the existing internal Python tool/connectors.
5. Keep the runtime/protocol file unchanged.
6. Set `USE_MOCK_ADAPTERS=false` in the workstation `.env`.
7. Run the adapter checks shown below.

The three workstation implementation files are local-only and git-ignored. The web application never imports them.


## Snapshot-only source access

In the web application, real source calls are initiated only from the **Snapshots** workflow. AutoSys snapshot generation performs `fetch_topology` for the previous local calendar day (COB = today - 1 day). Process Scheduler first uses `list_roots` to populate the topology selector, then uses `fetch_topology` for the selected topology. Browse, Compare, Search, and Export consume persisted snapshots and must never call the bridge.

## What source-specific code may do

The source providers may:

- call the existing AutoSys / Process Scheduler Python connector functions;
- authenticate using the bank-approved workstation mechanism;
- paginate/retry idempotent source reads with bounded limits;
- map native DTOs into `scheduler-bridge/v1` jobs/dependencies;
- preserve useful source metadata in `attributes`;
- declare field support and evidence.

They must not modify comparison logic, identity matching, UI, snapshot persistence, or internal engine models.

## Stable handoff

The only shared contract is documented in `docs/workstation-connector-protocol-v1.md` and implemented by the portable translator in `app/adapters/bridge_contract.py`.

The workstation side never imports:

```text
app.models
app.adapters
app.services
```

This is intentional. A future refactor of `SnapshotJob`, `TopologySnapshot`, FastAPI routes, or comparison services must not require a workstation connector rewrite.

## Mapping rules

- Stable native/source ID -> `job_uid`.
- Scheduler display name -> `scheduler_job_name`.
- Container/box/topology membership -> `parent_uid`.
- Native status -> normalized `status` plus original `status_raw`.
- Explicit execution predecessor/trigger -> `dependencies[]`.
- Verified AutoSys/JIL equivalent -> `autosys_jil`.
- Verified runtime equivalent -> `autosys_run`.
- Process Scheduler native detail -> `process_scheduler`.
- Non-comparison source fields -> `attributes`.

Containment is not execution dependency. Never derive edges from tree position/order.

## Failure semantics

The connector must return `ok=false` rather than an empty snapshot when retrieval is incomplete, including authentication failure, timeout, source 5xx/gateway failure, parse/schema failure, or incomplete pagination.

## Verification

```cmd
set USE_MOCK_ADAPTERS=false
python -m app.adapters.check --environment autosys-u1 --scheduler autosys --as-of 2026-10-07
python -m app.adapters.check --environment ps-u5 --scheduler process_scheduler --as-of 2026-10-07
```

The contract checker validates health, scheduler/context consistency, duplicate IDs, dangling parents/dependencies, strict field-support declarations, and normalized snapshot integrity.
