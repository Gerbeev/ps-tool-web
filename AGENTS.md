# Agent Instructions: Scheduler Snapshot + Workstation Bridge Architecture

## Non-negotiable boundary

The portable web project must remain independent from bank-local AutoSys and Process Scheduler implementation code.

Real connectivity is out-of-process only:

```text
Snapshots UI
  -> app.services.snapshot_generation
  -> SchedulerAdapter
  -> ExternalBridgeAdapter
  -> scheduler-bridge/v1 (stdin/stdout JSON)
  -> workstation_connectors/autosys_connector.py
     or workstation_connectors/process_scheduler_connector.py
  -> existing bank-local Python tool/API
```

Never add `bank_autosys*.py`, `bank_process_scheduler*.py`, dynamic adapter imports, direct Cosmos access, or bank-only imports under `app/`.

## Snapshot architecture

`Snapshots` is the only web workflow allowed to access scheduler sources.

- AutoSys: choose environment, capture the current business date.
- Process Scheduler: choose environment, call `list_roots` through the bridge, select an existing topology, then capture it.
- Every successful capture becomes a new immutable catalog entry with its own `snapshot_id`.
- Runtime snapshot files live under `SNAPSHOT_DIR` and are git-ignored.

Browse, Compare, Search, and Export are snapshot consumers only. They must not import or call:

```text
get_adapter
fetch_snapshot
ExternalBridgeAdapter
list_roots
```

Browse selects `environment + snapshot_id`. Compare selects `environment + snapshot_id` independently for both sides. Neither view owns business-date/topology source controls and neither view refreshes data.

## Frozen workstation contract

`scheduler-bridge/v1` is the stable handoff. Existing v1 field meanings and operation semantics must not be changed incompatibly. If an incompatible change is unavoidable, introduce `scheduler-bridge/v2` rather than silently changing v1.

The workstation connector files must not import:

```text
app.models
app.adapters
app.services
```

Only the portable translator in `app/adapters/bridge_contract.py` maps the frozen wire DTO into current internal models.

## Workstation implementation surface

On the bank workstation, source-specific code belongs only in the persistent local connector directory configured by `PS_TOOL_CONNECTOR_DIR`:

```text
bridge_v1_runtime.py              # keep unchanged
autosys_connector.py              # bank-local AutoSys mapping
process_scheduler_connector.py    # bank-local PS mapping
```

The two provider scripts may call the existing internal Python tool/connectors, authenticate using approved local mechanisms, paginate/retry bounded idempotent reads, and map source DTOs into bridge-v1 dictionaries.

They must not implement comparison logic, identity matching, UI behavior, or snapshot persistence.

## Mapping rules

- Stable source ID -> `job_uid`.
- Scheduler display name -> `scheduler_job_name`.
- Container/box/topology membership -> `parent_uid`.
- Native status -> normalized `status` plus unchanged `status_raw`.
- Explicit execution predecessor/trigger -> `dependencies[]`.
- Verified AutoSys/JIL equivalent -> `autosys_jil`.
- Verified runtime equivalent -> `autosys_run`.
- Process Scheduler native detail -> `process_scheduler`.
- Non-comparison source fields -> `attributes`.

Containment is not execution dependency. Never infer dependency edges from tree position, ordering, or naming.

## Failure semantics

A connector must return `ok=false` instead of an empty/partial snapshot when retrieval is incomplete, including authentication failure, timeout, incompatible schema, parse failure, or incomplete pagination.

The Snapshots workflow validates the normalized snapshot before catalog publication. Failed generation must leave all existing snapshots untouched.

## Security and data handling

- No credentials/tokens/certificates in the repository, environment YAML, bridge payloads, or logs.
- Do not log raw source DTOs or sensitive command output.
- Runtime snapshots are bank-sensitive and remain under git-ignored `data/runtime/` (or configured `SNAPSHOT_DIR`).
- Workstation connector implementations remain local and are not committed.
- The bridge launcher must keep `shell=False`, bounded timeout, response-size limits, protocol/version checks, and request-ID validation.

## Required validation

```bash
python -m app.adapters.check --environment <autosys-env> --scheduler autosys --as-of <YYYY-MM-DD>
python -m app.adapters.check --environment <ps-env> --scheduler process_scheduler --as-of <YYYY-MM-DD>
python -m scripts.verify_checkout --runtime
python -m pytest -q
```

The test suite includes a source-isolation regression guard. Do not remove or weaken it: Browse, Compare, and Export must continue to function after generated snapshots exist even when adapter access is made to fail deliberately.
