# Refactoring and optimization report — 2026-10-07

## Scope

Audited and refactored the standalone Python 3.11+ log analyzer supplied in `log_analyzer_single_config.zip`. The existing Windows launchers, CLI parameters, interactive menu, output CSV column names, `config.json` layout, environment allowlist, and `.state` format remain compatible.

The following **behavior is deliberately unchanged**:

- `inventory` (default) reads only directory entries and filesystem metadata; no source `.log` content is opened.
- `enrich` opens source logs **read-only**, uses up to `read_workers` bounded concurrent workers, and resumes append-only files from completed-line byte checkpoints.
- Reports remain at `output/<ENV>/<YYYYMMDD>/jobs.csv`, with an environment-specific incremental state in `.state/<YYYYMMDD>.json`.
- PROD, U5, U1, and U6 are the only approved environments. Their configured source paths remain unchanged.
- Interactive terminal progress and ETA stay available; redirected stdout remains plain-text.
- New or previously enriched COBs are not finalized by inventory; finalized COBs require `--force` to reopen.

## Changes

| Area | Problem | Change |
| --- | --- | --- |
| Log-line reader | Naive repeated concatenation of the unfinished line reallocates increasingly large buffers | Retain the fast immutable-bytes path for short lines; use an in-place bytearray and suffix-only separator searches for long lines |
| Log file discovery | `inventory_cob` and `update_cob` maintained duplicate metadata discovery / nested COB handling logic | Introduced `iter_cob_logs()` and a typed `CobLog` data structure shared by both modes |
| COB statistics | Eight positional result fields were easy to interchange | Replaced positional tuples with field-addressable `CobResult` (a `NamedTuple`, so tuple unpacking still works) |
| Config loading | CLI parsed the same JSON twice and CLI/menu duplicated validation | Introduced `validate_config()` and `policy_from_config()`; CLI reads its config exactly once |
| Config safety | Direct library calls could output reports under unspecified environment codes; unsafe UTF-7 could be selected | Validate environment membership and reject UTF-7 checkpoints and invalid CSV delimiters |
| State resilience | Open manifests containing malformed per-file signatures could interrupt an entire run | Detect invalid state entries and rebuild the affected COB state through the normal safe scanner |
| CSV compatibility | Extra or missing keys in older cached rows could fail `DictWriter` or emit unwanted columns | Project rows onto the fixed schema and escape spreadsheet formula prefixes for source-controlled text fields |
| Windows runner | Launcher behavior was inconsistent | All CMD launchers now require Python 3.11+ through the `python` command only; no Python Launcher (`py`) fallback is used |
| Regression coverage | Edge cases above were not independently exercised | Added `tests/test_refactor.py` with 8 focused regressions |

There are no third-party runtime dependencies and no database migrations. Existing valid state files and reports can be reused.

## Verification

```cmd
cd tools\log_analyzer
python -m unittest discover -s tests -v
python tests\benchmark_perf.py
```

- Baseline: **84/84** automated tests passed.
- Current build: **97/97** automated tests passed.
- `python -m compileall` and the new targeted edge-case tests passed.
- Testing was performed on **local synthetic files under Linux**, not on corporate Windows UNC/SMB infrastructure; Win32 shared-handle behavior still needs an approved on-network acceptance run.

### Local synthetic benchmark (one run per build)

Workload: 2,500 logs; one approximately 100 MiB log; 4 content readers. Times are elapsed wall-clock seconds and are **not** an SMB performance guarantee.

| Operation | Before | After |
| --- | ---: | ---: |
| Initial metadata-only inventory | 0.13 s | 0.11 s |
| No-op inventory | 0.08 s | 0.07 s |
| Initial enrichment | 9.30 s | 8.81 s |
| No-op enrichment | 0.07 s | 0.09 s |
| Inventory after one append | 0.17 s | 0.18 s |
| Enrichment after one append (52-byte suffix) | 0.17 s | 0.17 s |

A parser-only microbenchmark (280,000 short lines, ~10.9 MiB) measured **0.054 s before vs. 0.056 s after**; one very long line (~12 MiB) measured **0.025 s before vs. 0.011 s after**. These short synthetic tests are sensitive to CPU scheduling and filesystem caching; do not interpret small differences as significant throughput gains.

## Operational caveats

1. **Completion semantics:** `job_status=Completed` in enriched rows is a legacy placeholder, not authoritative scheduler confirmation. Real success/failure must come from AutoSys/Process Scheduler or verified markers.
2. **Finalization:** a closed COB's contents are not traversed. To detect late changes, select the COB with `--date` and `--force`; mtime-based closure remains heuristic.
3. **Mid-file rewrites:** checkpoint prefix anchors sample the file's head and parsed tail, rather than hashing every byte. They cannot detect every in-place edit to the middle of a large log. Force-reparse known rewritten logs.
4. **SMB and privacy:** output CSV and `.state` JSON can contain confidential error text. Store them on approved internal storage with appropriate access control and retention. Benchmark on an approved share with a realistic file count before selecting a worker count.
5. **Windows acceptance:** verify the 3 `.cmd` launchers and concurrent scheduler appends on a company workstation; they cannot be executed in the local Linux test environment.


## 2026-10-07 COB root-window correction

- COB discovery is now strictly root-level: only direct `Logs/YYYYMMDD` directories are candidates.
- Non-COB root directories/files are ignored and never recursively traversed.
- Future-dated COB directories are ignored during normal scans.
- Normal scans select only the newest `incremental.cob_scan_limit` existing COB folders (default `7`).
- `--date YYYYMMDD` remains an explicit historical override for a root-level COB outside that window.
- UAT defaults follow `CVA\UAT\_U5|_U1|_U6\Logs`; PROD remains unchanged.
- Added regressions for duplicate-looking COBs inside ignored folders, scan-window limiting, explicit-date override, and setting validation.
