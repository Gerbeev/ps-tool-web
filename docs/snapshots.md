# Immutable Snapshot Workflow

## Contract

`Snapshots` is the only web workflow allowed to read AutoSys or Process Scheduler.

The runtime dependency direction is fixed:

```text
Snapshots route
  -> snapshot_generation
      -> SchedulerAdapter / scheduler-bridge/v1
      -> validation
      -> SnapshotCatalogStore

Browse route  -> SnapshotCatalogStore
Compare route -> SnapshotCatalogStore
Export route  -> comparison session or SnapshotCatalogStore
Search route  -> loaded Browse/Compare session
```

Browse and Compare must not import `get_adapter`, `fetch_snapshot`, `ExternalBridgeAdapter`, or any connector implementation.

## AutoSys generation

AutoSys generation accepts only an environment. The application creates a `ComparisonContext` using the previous local calendar day as COB (`today - 1 day`) and asks the configured adapter for a topology snapshot. There is no business-date selector in Browse or Compare; the captured date is part of the immutable snapshot metadata.

## Process Scheduler generation

Process Scheduler generation has two source operations, both exposed only from the Snapshots view:

1. `list_roots` retrieves available topology names for the selected environment.
2. `fetch_topology` retrieves the selected topology and normalizes it into the engine model.

The chosen topology is stored in the snapshot context and catalog record. Browse and Compare only select a saved snapshot ID.

## Persistence

`SnapshotCatalogStore` writes runtime state under `SNAPSHOT_DIR`, defaulting to:

```text
data/runtime/snapshots/
  index.json
  <snapshot-id>.snapshot.json.gz
  <snapshot-id>.snapshot.json.gz
  ...
```

Each catalog record contains:

- `snapshot_id`
- capture/fetch timestamps
- scheduler and environment
- frozen `ComparisonContext`
- business date or topology scope
- job/dependency counts
- payload filename and SHA-256 checksum

Snapshot payloads are immutable. A new capture always produces a new ID and file. The index is published atomically after the snapshot payload is complete.

## Failure behavior

Source fetch and validation happen before catalog publication. If adapter/bridge access fails or snapshot validation reports errors, no catalog record is added and all existing snapshots remain unchanged.

A snapshot whose payload is missing or fails its checksum is rejected when Browse/Compare attempt to load it.

## Source isolation

This boundary is deliberate for the bank-workstation deployment model. The web project can evolve independently while the workstation connector scripts remain fixed behind `scheduler-bridge/v1`.

The test suite contains an explicit regression test that generates snapshots, replaces the adapter factory with a function that raises immediately, and then verifies that Browse and Compare still work. This guards against accidental live-source access being reintroduced later.


## Snapshot naming and deletion

- AutoSys display name: `<ENV>-AutoSys_<YYYY-MM-DD>_<HH-MM-SS>` using local capture time.
- Process Scheduler display name: `<ENV>-ProcessScheduler_<YYYY-MM-DD>_<TOPOLOGY>` using local capture date.
- AutoSys source `business_date` is always the previous local calendar day (`today - 1 day`).
- Snapshots can be deleted only from the Snapshots tab; deletion removes both the catalog entry and payload file.
