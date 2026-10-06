# Canonical mock reference dataset

## Purpose

`data/mock/reference_topology_2500.jsonl` is the single source of truth for deterministic mock scheduler data used before real endpoint adapters are available.

The file is environment-neutral. It does **not** contain UAT/PROD environment tokens in individual job records. A snapshot is materialized for a selected environment by inserting that environment's token into the native scheduler job name.

This makes one fixture reusable for UAT, PROD, PIE, or future environments while keeping logical job identity stable across environments.

## Dataset shape

- exactly **2,500 scheduler nodes**;
- **25 synthetic business groups**;
- every group has a different synthetic four-digit business code;
- **10 boxes per business group**: one application root plus nine nested section boxes;
- **90 executable jobs per business group**: ten jobs under each section box;
- **2,225 execution dependency edges**;
- AutoSys-equivalent types: `BOX`, `CMD`, `FW`;
- semantic executable types include command, .NET, file watcher, stored procedure, report, and publisher jobs;
- deterministic statuses and runtime timestamps so repeated tests produce identical results;
- synthetic Process Scheduler schedule/detail fields based on the observed full-job detail shape (`Schedule`, `StartAtTime`, `StartAtTimeForce`, native status/timestamps, context and box values).

Hierarchy per business group:

```text
Application_Box
├── Admin_Box
│   ├── ... File_Watcher
│   ├── ... Extract
│   ├── ... Transform
│   └── ...
├── Audit_Box
├── DP_ADP_Box
├── DP_IM_Box
├── DS_FG_Box
├── Reports_Box
├── QuarterEnd_Box
├── Reconciliation_Box
└── Publishing_Box
```

The environment-specific native name is produced from:

```text
common_prefix + business_code + environment_token + job_specific_name
```

Only `environment_token` changes between environment projections. The business code and job-specific part stay unchanged and therefore form the cross-environment logical identity.

## Runtime integration

`app/mock_reference.py` loads the JSONL fixture once and materializes a `TopologySnapshot` for the requested scheduler/environment.

The default mock dataset is:

```text
MOCK_DATASET=reference_2500
```

`legacy_small` remains available for focused unit tests. `MOCK_JOB_COUNT>0` remains an explicit synthetic scalability override.

The reference fixture is consumed through the existing mock adapters only; there is no mock database and no duplicate per-environment dataset. This keeps the temporary implementation close to the future adapter boundary: real adapters can later replace retrieval while the comparison engine continues to consume `TopologySnapshot`.

## Baseline invariant

The reference dataset is an equality baseline. Two projections of the same reference file for different environments must compare as:

```text
matched = 2500
left_only = 0
right_only = 0
status_mismatches = 0
parameter_mismatches = 0
timing_mismatches = 0
identity_conflicts = 0
```

The native job names and native `box_name` values are allowed to differ by the environment token. The comparison engine normalizes structured parent job identity before comparing `box_name`.

Future negative/migration test cases should be implemented as explicit overlays/deltas on top of this baseline rather than by cloning and manually editing the complete 2,500-job fixture.

## Regeneration

The checked-in reference file is generated deterministically by:

```text
python scripts/generate_reference_topology.py
```

Regeneration must still produce exactly 2,500 jobs.

## Process Scheduler full-detail projection

When the canonical fixture is materialized as Process Scheduler, every synthetic `SnapshotJob` also receives a typed `process_scheduler` source reference. This exercises the same model shape expected from the future endpoint adapter without duplicating the 2,500-row fixture.

The canonical records now carry environment-neutral `schedule`, `start_at_time`, and `start_at_time_force` values. Native job names, `Box`, `Context`, runtime status and timestamps are generated at materialization time. `Context` is the synthetic topology ID; `Box` is the synthetic parent name (or topology ID for a root). These are surrogate semantics for testing and are not asserted to be the bank endpoint's final hierarchy contract.
