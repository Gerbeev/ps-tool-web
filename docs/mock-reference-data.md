# Canonical mock reference dataset

## Purpose

`data/mock/reference_topology_2500.jsonl` is the single healthy canonical source for deterministic mock scheduler data used before workstation bridge connectors are available.

The file is environment-neutral. It does not contain concrete UAT/PROD tokens in individual job records. A snapshot is materialized for a selected environment by inserting that environment token into the native scheduler job name.

The default migration demo then layers `data/mock/u1_to_u5_migration_overlay.jsonl` onto **Process Scheduler U5 only**. AutoSys U1 remains the healthy reference side.

## Dataset shape

- exactly **2,500 scheduler nodes**;
- **25 synthetic business groups** with different synthetic four-digit business codes;
- **10 boxes per business group**: one application root plus nine section boxes;
- **90 executable jobs per business group**;
- **2,225 canonical execution dependency edges**;
- AutoSys-equivalent types: `BOX`, `CMD`, `FW`;
- semantic executable types include command, .NET, file watcher, stored procedure, report and publisher jobs;
- every canonical job is successful and has deterministic but varied runtime timestamps;
- runtimes are dependency-aware: chained leaf jobs start after their predecessor finishes;
- every job has a non-empty synthetic description and source-specific detail data.

Environment-specific names follow:

```text
common_prefix + business_code + environment_token + job_specific_name
```

Only the environment token changes between environment projections. Cross-environment identity keeps business code + job-specific name.

## Default U1 -> U5 migration scenario

The local app enables only these environments by default:

```text
AutoSys:            U1
Process Scheduler:  U5
```

U1 is the healthy reference: **2,500/2,500 jobs successful**, exit code `0`, with realistic staggered start/end times across the batch window.

U5 is produced from the same canonical fixture plus the deterministic migration overlay. Normal migrated jobs start **25 seconds later** than U1, which stays inside the configured 60-second timing tolerance. Controlled defects are then injected:

| Issue | Count | Simulation |
| --- | ---: | --- |
| Missing job | 12 | Job is absent from the U5 snapshot |
| Failed | 18 | `Failed`, exit code `8` |
| Long running | 10 | `Running`, start present, no finish |
| Activated | 12 | raw PS status `Activated`, no runtime yet |
| Waiting | 8 | raw PS status `Waiting`, no runtime yet |
| OnIce | 6 | disabled/on-ice |
| Cancelled | 4 | `Cancelled`, exit code `143` |
| Late but successful | 15 | successful job shifted far outside timing tolerance |
| Slow but successful | 12 | successful job takes 10–75 minutes longer than U1 while retaining a comparable start time |
| Command drift | 5 | migrated command differs |
| Machine drift | 5 | execution machine differs |
| Schedule drift | 3 | days-of-week differs |
| Dependency removed | 4 | explicit incoming dependency removed |

The 12 missing jobs also remove dependency edges that reference those absent jobs, so dependency mismatches include both direct dependency defects and realistic cascade from missing jobs.

Expected U5 status population after removing the 12 missing jobs:

```text
Success   2430
Pending     20   # 12 Activated + 8 Waiting
Failed      18
Running     10
OnIce        6
Cancelled    4
Total     2488
```

The expected comparison contract for AutoSys U1 -> Process Scheduler U5 is regression-tested:

```text
left total                 2500
right total                2488
matched                    2488
left only                    12
right only                    0
status mismatches            58
timing mismatches            27
execution-time mismatches    12
identity conflicts             0
not comparable                0
```

Parameter mismatch counts are also asserted in tests so changes to normalization or comparison semantics cannot silently change the demo scenario.

Execution time is derived from each completed job's timestamps (`actual_end - actual_start`) and shown as `HH:MM:SS`. The comparison table always shows the signed `Exec Δ (R−L)` when both sides have complete runtime timestamps. The default execution-time mismatch threshold is **300 seconds**; the 12 `slow_success` records are deliberately above that threshold. Positive deltas mean U5 is slower. Running/pending/on-ice jobs without a finish timestamp have no completed execution time yet and are not classified as execution-time mismatches.

## Runtime integration

`app/mock_reference.py` loads the canonical JSONL once and materializes a `TopologySnapshot` for the requested scheduler/environment. The optional scenario overlay is applied only when scheduler/environment match the overlay target.

Defaults:

```text
MOCK_DATASET=reference_2500
MOCK_REFERENCE_PATH=data/mock/reference_topology_2500.jsonl
MOCK_SCENARIO=u1_to_u5_migration
MOCK_SCENARIO_PATH=data/mock/u1_to_u5_migration_overlay.jsonl
```

Set `MOCK_SCENARIO=none` to inspect the pure equality baseline. `legacy_small` remains available for focused tests, and `MOCK_JOB_COUNT>0` remains an explicit scalability override.

## Browse/detail behavior

Every canonical job materializes enough data to exercise the job-detail UI. AutoSys projections expose populated JIL/run data; Process Scheduler projections expose typed native detail plus the normalized comparison projection.

For U5 issue jobs, `attributes.mock_migration_issue` identifies the injected defect, so the detail panel/source data remains inspectable during manual testing.

Canonical `job_ref` values contain `/` because they describe hierarchy. They remain in `scheduler_native_id` and `attributes.reference_job_ref`, while application `job_uid` values are URL-safe opaque identifiers for Browse/Compare routes.

## Regeneration

Both files are deterministic and generated together by:

```text
python scripts/generate_reference_topology.py
```

Regeneration must still produce exactly 2,500 canonical jobs and the configured migration issue counts.
