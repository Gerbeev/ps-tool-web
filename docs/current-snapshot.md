# Current Comparison Snapshot

The application deliberately keeps **one current comparison snapshot only**. There is no snapshot history, revision browser, retention workflow, or snapshot database.

## Lifecycle

1. Build the left and right comparison contexts (environment, scheduler, business date/run/topology and filters).
2. `Compare snapshot` reuses the durable current pair when both contexts match exactly.
3. If no current pair exists, or the selected parameters differ, both scheduler sources are fetched and validated.
4. `Refresh & compare` always fetches both sources again.
5. A new pair becomes current only after **both** fetches and validations succeed.
6. Browse/Compare/tree/detail/export then operate on the frozen snapshots rather than re-fetching scheduler data.

## Storage

Runtime files live under `CURRENT_SNAPSHOT_DIR` (default `data/runtime/current`):

```text
manifest.json
left-<capture-id>.snapshot.json.gz
right-<capture-id>.snapshot.json.gz
```

Only the files referenced by `manifest.json` are active. A new generation is fully written before `manifest.json` is atomically replaced; old generation files are deleted after the successful switch. This gives replacement semantics without maintaining history.

The manifest records:

- capture timestamp;
- exact left/right contexts;
- per-side fetch timestamps;
- scheduler/environment;
- job and dependency counts;
- compressed payload filenames and SHA-256 hashes.

## Staleness

Context equality is exact. Changing business date, run/topology, environment, scheduler, endpoint or filters means the current snapshot does not match and a new capture is required. The application never silently analyzes an old snapshot under new parameters.

## Failure behavior

A failed or invalid fetch on either side does not replace the current durable snapshot. The previous current snapshot remains available for analysis.

## Browse

Browse reuses a side of the current comparison snapshot when its context matches exactly. Browsing another context can still fetch data for exploratory use, but that standalone Browse load does not replace the current comparison snapshot.
