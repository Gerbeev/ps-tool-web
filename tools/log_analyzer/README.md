# Standalone Job Log Analyzer

Independent console application for building an **immediate metadata-only inventory**, then optionally enriching the same COB-based CSV reports from log contents. **Python 3.11+ only; no pip packages, database, application server, or scheduler adapters required.**

**Refactoring (2026-10-07):** Consolidated config validation, optimized long-line parsing, hardened manifest/CSV handling, and restricted normal COB discovery to the newest configurable root-level date folders. See [`REFACTOR_REPORT.md`](REFACTOR_REPORT.md) for the changes, local performance comparison, preserved compatibility, and Windows/SMB acceptance notes.

## Two-stage workflow (recommended)

```cmd
cd tools\log_analyzer
run.cmd PROD --mode inventory
run.cmd PROD --mode enrich
```

- **Inventory (default)**: uses only directory listing + filesystem metadata. Does not open `.log` contents even for new 100 MB files. Immediately writes `output/PROD/<COB>/jobs.csv` with COB, system, job name, full source path, byte size, last modification time, and activity. Detailed metrics remain **empty** (not zero); `job_status=Unknown`, `enrichment_status=Pending`.
- **Enrich (explicit)**: visits open COBs and parses only `Pending`/`Stale`/modified files. Continues from the last completed-line checkpoint for append-only logs. Updates the **same CSV** with execution times, duration and warning/error/restart counters; `enrichment_status=Enriched`.
- **Refresh**: running inventory again after log changes marks outdated rows `Stale` and clears old detailed metrics, without accessing the log contents. A subsequent enrich refreshes only those rows. Inventory never closes a COB on its own; enrichment can finalize an aged/quiet COB once **all** its rows are enriched.
- **Existing state**: previous `.state` files are reused (without rereading unchanged enriched logs). Previously closed COBs remain skipped unless targeted with `--date YYYYMMDD --force`.

Recommended schedule: run inventory more often (e.g. 15–30 min after testing SMB overhead) and enrichment less often (e.g. hourly or manually), especially when batch processing is busy. Both operations use a local/output-side mutex; neither modifies source files.

## Windows quick start (interactive menu)

Open the `tools\log_analyzer` folder and double-click the CMD launchers in this order:

1. **`setup.cmd`** — validates that Python 3.11+ is available through the `python` command, validates the JSON config, and checks dependencies. This tool uses Python's standard library only, so there is nothing to install with pip.
2. **`start.cmd`** — opens the console menu. It also works without running setup first if Python is already installed.

You can also invoke `start.cmd` from an existing Command Prompt. The tool stays in the console until you select `0`.

### Live console progress (both modes)

When launched in a Windows terminal, `inventory` and `enrich` display a **single, dynamically refreshed dashboard** rather than continuously appending console lines. The display refreshes about four times per second, including while a large log is being read. It shows the environment, mode, current COB, COB count, per-COB file progress, completed/total file count, current-file name, enriched/inventoried/cached/skipped counts, elapsed time, processing rate, ETA for the current COB, approximate remaining time for all COBs, and recent warnings. The source logs are never opened by the dashboard itself.

```text
 JOB LOG ANALYZER  |  PROD  |  ENRICH
======================================================================
 Stage         : Enriching
 COB           : 20261005  (2/8)
 Progress      : [##################......................] 45.0%
 COB files     : 1,125 / 2,500
 This COB      : 29.4 files/s  |  ETA 00:00:47
 All COBs ETA  : ~00:04:10 (rough estimate)
 Total handled : 3,625  |  Enriched: 430  |  Inventoried: 0
 Cached        : 3,195  |  Skipped: 0  |  Closed COBs: 0
 Elapsed       : 00:02:03  |  Written reports: 1
 Last file     : Downstream/job_1125.log  |  Queued reads: 4
----------------------------------------------------------------------
 Recent events:
  CSV: .../output/PROD/20261004/jobs.csv (2500 jobs; ...)
```

The example is illustrative, not a performance measurement. File totals are **exact within the active COB**, counted from that COB's normal metadata enumeration. The number of COBs is also known; the overall ETA extrapolates from COBs processed so far and is less reliable when file sizes vary substantially or many COBs are already closed. While the program is enumerating a COB, it displays `counting...`, then switches to the known total. No extra read of source-log *contents* is performed to build the progress display.

The dashboard runs automatically in interactive terminals that support ANSI/Windows Virtual Terminal; when output is redirected to a file/pipe, or when using `--no-progress`, the original line-oriented CLI output is preserved. To keep all detailed diagnostics, use for example `run.cmd PROD --mode enrich --no-progress > analyzer-run.log 2>&1` (write the run log outside the source Logs share). The live screen shows the latest events; after it closes, the terminal shows the final summary and up to five recent warnings. `Ctrl+C` restores the terminal and stops the scan; completed COB reports stay intact.

```text
================================
       JOB LOG ANALYZER
================================
1. Inventory logs (metadata only)
2. Enrich reports (parse log contents)
9. Settings
0. Exit
Select:
```

**Option 1 — Inventory logs**: select an environment and confirm `Start inventory? [y/N]`. Uses `os.scandir` file names and stat data only, never opens or parses `.log` contents.

**Option 2 — Enrich reports**: select an environment and confirm `Start enrichment? [y/N]`. Parses new and changed logs, reuses checkpoints and cached results for unchanged files, and updates the same COB reports.

**Option 9 — Settings**:

```text
1. Edit environment log path
2. Edit environment description
3. Change log file encoding
4. Minimum active COB days
5. Quiet hours before COB finalization
6. Recent log activity window (minutes)
7. Concurrent SMB readers (1-16)
8. Latest COB folders to scan
0. Back
```

Settings are written atomically to the single **`config.json`** file. The interactive menu and CLI both read this file by default. An old `config.local.json` left by a previous release is **ignored** and can be deleted. For automation/tests, the direct CLI still accepts an explicit `--config PATH`; normal operation needs only `config.json`. Treat this file as deployment configuration and avoid committing machine-specific modifications if you use Git.

**Option 0 — Exit**: closes the menu normally. Errors during a scan show an English message and return to the menu. Completed per-COB reports are published atomically, independently; a later COB failure does not roll back earlier COB reports.

**Output (grouped by COB)**: each business date gets one report in `tools\log_analyzer\output\<ENV>\<YYYYMMDD>\jobs.csv`.

```text
output/
  PROD/
    .state/                  # Internal incremental manifests; do not delete
      20261002.json
      20261003.json
    20261002/
      jobs.csv
    20261003/
      jobs.csv
  U5/
    20261002/
      jobs.csv
```

The analyzer treats only **direct children of the configured `Logs` root** whose names are valid `YYYYMMDD` dates as COB folders. Non-COB files and directories at the root are ignored completely and are never traversed. From the eligible dates up to the current local date, a normal run selects only the newest `cob_scan_limit` folders (default **7**). This prevents old archive/service directories and thousands of historical COBs from being scanned. The `system` column is the first directory **immediately under that COB folder** (for example `Downstream` or `Upstream`), and logs may be nested further below the system folder. Logs directly inside the COB folder have an empty `system` value. Subsequent scans only replace **changed** reports. An explicit `--date YYYYMMDD` is a manual override that may target an older root-level COB outside the normal window. Output is local to this tool and may contain confidential log errors; keep it on approved storage.

## Configuration

Only four environments are available in both the interactive menu and `--env` CLI selection. The source folder name differs from the displayed environment code for U5, U1 and U6:

| Environment | Source folder | Default Windows UNC log root |
| --- | --- | --- |
| `PROD` | `PROD` | `\\ldnroot\data\IBCT\CVA\PROD\Logs` |
| `U5` | `_U5` | `\\ldnroot\data\IBCT\CVA\UAT\_U5\Logs` |
| `U1` | `_U1` | `\\ldnroot\data\IBCT\CVA\UAT\_U1\Logs` |
| `U6` | `_U6` | `\\ldnroot\data\IBCT\CVA\UAT\_U6\Logs` |

`config.json` ships with all four full UNC paths. PROD remains under `CVA\PROD\Logs`; U5/U1/U6 are under `CVA\UAT\_<ENV>\Logs`, matching the UAT directory layout. Check the network share and permissions on your deployment host. Environment names and source folders are intentionally separate: output reports always use `output/PROD`, `output/U5`, `output/U1`, or `output/U6` (without leading underscores).

New environment creation has been removed from Settings. Unapproved names (including `P1`) are rejected by the direct CLI, even if they appear in a custom JSON configuration. Configuration is no longer merged with local overrides: the four source paths are maintained in `config.json`, and Settings edits that same file.

Paths are environment-specific and can point to local disks, mapped drives or UNC shares. Relative paths in custom config files resolve relative to that config file. Encoding may be changed (e.g. to `cp1252`) if the source logs are not UTF-8. The CLI reads source files only, and never writes, renames, changes permissions, or locks any source file. CSV, state, and output-only run mutex files are kept strictly outside the source Logs hierarchy.

## Run from the project root

```cmd
python tools\log_analyzer\analyze.py --env PROD --mode inventory
python tools\log_analyzer\analyze.py --env PROD --mode enrich
python tools\log_analyzer\analyze.py --env PROD --mode enrich --date 20261002
python tools\log_analyzer\analyze.py --env PROD --mode enrich --date 20261002 --force
python tools\log_analyzer\analyze.py --env U5 --output-dir C:\Temp\job-reports
```

Or, from the tool folder on Windows:

```cmd
run.cmd PROD
run.cmd PROD --mode enrich
run.cmd PROD --mode enrich --date 20261002
run.cmd PROD --mode enrich --date 20261002 --force
```

No `.venv` or external installation is needed. All Windows CMD scripts use the `python` command exclusively; `python.exe` must be available on `PATH`. `run.cmd` remains available for scripted/noninteractive use.

The default output is `tools/log_analyzer/output/<ENV>/<YYYYMMDD>/jobs.csv`; generated output is ignored by Git. `--output-dir` overrides the base output directory while preserving the environment/COB hierarchy. The `system` CSV column does **not** create additional output folders. The tool performs one root-level `os.scandir` of the Logs root, filters only direct `YYYYMMDD` directories up to today, and selects the newest configured number of COB folders. It never recursively searches non-COB root directories. In inventory mode it never opens log contents; in enrich mode it reads only new or changed `*.log` contents inside the selected COBs.

Optional `--delimiter ";"` supports semicolon-separated output for regional spreadsheet settings. The CSV uses `utf-8-sig` so Excel can detect UTF-8 reliably. Changing encoding, delimiter, configured source root, or analyzer state format invalidates the corresponding index; the next inventory remains metadata-only while enrichment will then scan affected open COBs once. The existing checkpoints are backward-compatible with previous state files.

## Incremental COB processing

The COB folder name is the **source of truth** for business date. It is **not computed as system date minus one day**: weekends, bank holidays, and delayed runs make that shortcut wrong. A job started on Tuesday and completed Wednesday remains under Tuesday's *COB folder* (which might represent Monday's business date) and is refreshed there.

On every run:

1. List the `Logs` root once, ignore every non-COB entry, discard future dates, and select only the newest `cob_scan_limit` valid root-level `YYYYMMDD` folders (default 7).
2. A **new** COB gets an inventory row per `.log` with only metadata; content is read only when enrichment is requested.
3. For an **open** COB, list `.log` filenames and gather file metadata (`size`, `mtime_ns`, `ctime_ns`) via `os.scandir`. Inventory reuses enriched rows if metadata is unchanged and marks changed rows `Stale`. Enrichment parses `Pending`/`Stale` files, resumes from the **last complete line byte offset** for append-only changes, and falls back to a full scan for new/rewritten/truncated files. Removed files are omitted from the report. A log appended after midnight updates the earlier COB.
4. A COB is **finalized only by enrichment**, and only when ALL are true: every row is `Enriched`, at least **7 calendar days** have elapsed since the COB date, the newest source-file modification was at least **72 hours** ago, and no parsing errors were detected. Finalized COBs are skipped entirely on later runs. This remains a grace-period heuristic, **not proof of scheduler completion**.
5. If a job writes to an old, already finalized COB unexpectedly, it will **not** be discovered automatically. Recover that specific COB with `run.cmd PROD --mode inventory --date 20261002 --force`, followed by `run.cmd PROD --mode enrich --date 20261002`. The COB can be finalized again when eligible.

Manifest files live under `output/<ENV>/.state/<COB>.json`. Active COB manifests contain file signatures, metadata rows and optional enrichment checkpoints; finalized manifests are compact. **Do not delete or edit `.state`** unless you intend to rebuild indexes. Back up `output/` (CSV reports and state) together. A legacy installation with existing CSVs but no manifests can be inventoried without reading content; enrich later to calculate full metrics.

Settings in `config.json` (or the `9. Settings` menu):

```json
"incremental": {
  "min_active_days": 7,
  "quiet_hours": 72,
  "recent_minutes": 5,
  "parallel_workers": 4,
  "cob_scan_limit": 7
}
```

`cob_scan_limit` controls how many of the newest existing root-level COB folders a normal run may process (default **7**, Settings option 8). It counts folders, not calendar days, so weekends/holidays with no folder do not consume the window. `recent_minutes` controls the diagnostic window, not COB finalization. It defaults to five minutes and can be edited in Settings option 6. `parallel_workers` sets the maximum number of log files enriched concurrently (default **4**, range 1-16); configure it using Settings option 7. The implementation uses a bounded thread pool because enrichment is SMB/file-I/O bound; setting it to **8** means up to eight logs are parsed concurrently, not eight spawned Python OS processes. Start with 4 on a shared corporate SMB volume and test 2 vs 4 vs 8 with IT/operations approval before increasing concurrency. The separate `min_active_days=7` finalization grace period covers weekends and ordinary delayed completions. Increase `min_active_days` or `quiet_hours` for unusually long-running jobs; changing either setting **does not reopen COBs already finalized**. For guaranteed finality, the upstream scheduler must provide an authoritative COB-completed event or marker; modification-time heuristics alone cannot prove a batch is finished.

**Operational use**: Schedule `run.cmd PROD --mode inventory` and `run.cmd PROD --mode enrich` separately with Windows Task Scheduler. The analyzer does not stay resident or watch files between invocations. Avoid very frequent scans when the share is busy; 15–30 minutes is a possible initial inventory interval after measuring SMB metadata load. One writer per environment/output root is enforced via `output/<ENV>/.analyzer.lock`. If a process was forcibly killed and left a lock, verify no analyzer process is running before deleting that lock file. Different environments can run independently.

## SMB performance and correctness

- **Initial inventory:** no file content opened, independent of whether a log is 1 KiB or 100 MiB. The only source I/O is directory listing and metadata. The **first enrichment** later scans each pending file in 256 KiB read chunks. Exact full-file counts require reading content at least once.
- **Appended logs:** each open COB manifest caches the last fully terminated line's **byte offset**, first/last timestamps, cumulative counters, last error, file identity, and small SHA-256 prefix anchors. On a safe append, only the newly appended suffix is parsed; the first 4 KiB and last 64 KiB of the *already parsed prefix* are checked to detect likely replacement/in-place rewrites. Depending on the old/new offsets this requires up to roughly 136 KiB of extra validation reads. File rotation/truncation or a detected rewrite falls back to a single full scan.
- **Incomplete lines:** if a writer ends the snapshot partway through a line, its bytes are not committed to the checkpoint. They are read with the next append; a stable unchanged terminal line can be included after the `recent_minutes` threshold. UTF-8/UTF-8 BOM, UTF-16/UTF-32 with BOM, BOM-less UTF-16 when its byte pattern is unambiguous, and normal single-byte encodings such as `cp1252` are supported. BOM/strong UTF-16 detection is performed per log file and can override a mismatched global encoding setting. A pathological log line longer than 16 MiB is skipped safely (the last known report row is preserved).
- **Unchanged files:** read no source-log content. Directory entries supply metadata without unnecessary per-file `is_file`/`stat` calls; a completely unchanged COB does not rewrite either its CSV or manifest.
- **Old COBs:** folders outside the newest `cob_scan_limit` window are not entered at all during normal runs, regardless of whether they are open or finalized in local state. Use explicit `--date YYYYMMDD` only for intentional historical recovery.
- **Bounded concurrency:** a fixed pool of 4 parallel read-only log workers by default, at most 16 configurable; no unbounded task queue and no mass file opens. The source-file handle is always created with Win32 read-only access and `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` on Windows. Workers never write or lock any shared source file; output, checkpoints, and the process mutex are local only.
- **Metadata/checkpoint integrity:** timestamp-parser semantic changes bump the state version, so open manifests are rebuilt once with the current extraction rules. Closed COBs remain closed unless explicitly rebuilt with `--date ... --force`. A hash of the small prefix samples does **not** mathematically prove the entire middle of a huge file was unchanged. If a producer rewrites old log content in place, use `--force` for that COB or connect an authoritative scheduler event/version.

**Local benchmark:** run `python tests/benchmark_perf.py` for a repeatable synthetic workload with 2,500 logs including one 100 MiB log. It measures initial metadata-only inventory separately from initial enrichment, no-op inventory/enrichment, and an append refresh. This is **not an SMB latency or throughput guarantee**; permissions, network metadata latency, AV scanning, and server load can dominate. Validate with a representative approved share.

**Console counters:** `Processed` means new/changed inventory rows in inventory mode, or logs parsed/updated in enrichment mode; `cached` = unchanged rows reused, `removed` = missing logs omitted, `COB reports` = CSVs written. `I/O` confirms inventory's zero content reads or enrichment's full/suffix scans. `WARN/ERROR` sums known enriched counts only (empty fields are not treated as measured zeroes).

## CSV columns

| Column | Calculation |
|---|---|
| `job_date` | Business/COB date from the nearest `YYYYMMDD` source folder, rendered in CSV as `YYYY-MM-DD`; e.g. `2026-10-02` |
| `system` | First directory directly under that COB folder, e.g. `Downstream`; blank when the log is directly under the date folder |
| `job_name` | Log filename without `.log` (the native environment token remains intact) |
| `job_status` | `Unknown` before enrichment; legacy value `Completed` after enrichment (**not proof of completion/success**). Use scheduler API for genuine status |
| `last_modified_time` | Source-file mtime from filesystem metadata, rendered as `YYYY-MM-DD HH:MM:SS.mmm` (UTC value, no `T` or timezone suffix) |
| `start_time` | First timestamp recognized by the ordered timestamp-model cascade near the beginning of a log record |
| `end_time` | Last timestamp recognized by the ordered timestamp-model cascade near the beginning of a log record |
| `duration` | Difference `end_time - start_time` as `HH:MM:SS`, with hours allowed above 24 |

Timestamp extraction uses an ordered cascade instead of a single mask. The fast path handles ISO/YMD records such as `2026-08-01 07:44:57,678`, `2026/08/01 07:44:57:678`, `2026.08.01T07:44:57.678Z`, and offset forms such as `+02:00`. Fallback models support a short logger prefix before the timestamp, compact YMD (`20260801_074457.678`), European DMY (`01/08/2026 07:44:57,678`), and month names (`01-Aug-2026 ...`, `August 01, 2026 ...`). One- or two-digit month/day/hour, `_` date separators, `:` or `.` time separators, fractional seconds up to nanoseconds, and `AM/PM` are accepted. Fallback search is limited to the first 96 characters before the timestamp so a date mentioned later in a message is not treated as the record timestamp. Timestamp extraction does not require an `INFO/WARN/ERROR` severity token. Output is normalized to `YYYY-MM-DD HH:MM:SS.mmm`; sub-microsecond source precision is truncated to Python datetime precision before CSV millisecond formatting.
| `restart_count` | Occurrences of the complete text following the first nonempty `INFO` record minus 1, minimum 0 |
| `warning_count` | Count of timestamped `WARN`/`WARNING` records |
| `error_count` | Count of timestamped `ERROR` records |
| `last_error` | Full last timestamped `ERROR` line (including timestamp, thread, and message) |
| `file_size_bytes` | Current file size from directory metadata; available during inventory |
| `enrichment_status` | `Pending`: never parsed; `Enriched`: metrics match last known parsed content; `Stale`: file metadata changed after enrichment, detailed metrics deliberately cleared |
| `enriched_at_utc` | UTC time of the last successful content extraction, rendered as `YYYY-MM-DD HH:MM:SS.mmm`; empty in `Pending` and `Stale` rows |
| `activity_status` | `RecentlyModified` if source mtime was within `recent_minutes` (default 5), `NotRecentlyModified` otherwise, `ClockSkew` if source timestamp is >60 seconds in the future. This does **not** prove the job is running or stopped |
| `path` | Full absolute source path to the `.log` file; disambiguates identical filenames in separate system/subfolders |

Before enrichment, `start_time`, `end_time`, `duration`, WARN/ERROR/restart counts and `last_error` are **empty**. Blank counts mean *not measured*, not zero. When a file changes, inventory hides stale content metrics and sets `enrichment_status=Stale` until the next enrich succeeds.

The observed format is:

```text
2026-10-05 00:01:01,993 [1] INFO : Feed Generator version: 264.10
2026-10-05 00:01:05,856 [1] WARN : Could not fully resolve settings
2026-10-05 00:20:05,901 [2] ERROR : Final error message
```

Continuation/stack-trace lines without a timestamped severity are **not** counted as separate events. `FATAL` and `CRITICAL` are not counted as `ERROR` because the requested rule is specifically `ERROR`.

For a source path like:

```text
\\ldnroot\data\IBCT\CVA\PROD\Logs\20261002\Downstream\IB_CT_CVA_1109_P1_DS_FG_OTCC_DMOReport_Frtb.log
```

`job_date` is `2026-10-02` in CSV and `system` is `Downstream`, while start/end can legitimately be on `2026-10-05`. The directory identifies the business date, not necessarily the log's calendar date. For example, `Logs\20261002\Upstream\Subfolder\job.log` gives `system=Upstream`.

## Production safety for Windows UNC / SMB shares

- On Windows the source file is opened with Win32 `CreateFileW` in `GENERIC_READ` mode and `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` sharing mode. The analyzer requests **no write or delete access** and does not call byte-range or advisory file-lock APIs. An existing writer with exclusive sharing may deny reads; such files are skipped and retried by the next scan, **not** forced open.
- Every shared source handle is closed after its own one-pass snapshot. On Unix-like systems the same reader uses read-only binary mode, without locks. There is **no long-running file watcher** or persistent open handle.
- Exactly one analyzer per environment/output directory is enforced with `output/<ENV>/.analyzer.lock`. **This file is not on the log source share unless you explicitly configure output onto that share.** Output must be separate from source; using an output directory that contains the source or is inside it is rejected.
- Inventory is metadata-only with no concurrent source-content readers. Enrichment uses a bounded pool of up to 4 concurrent read-only readers by default. Directory listing/stat and any enrichment reads still generate SMB traffic, so absolute zero production impact cannot be guaranteed.
- `mtime` is not a heartbeat: writers can buffer logs; metadata may be cached by SMB; timestamps may have clock skew. Five minutes is a diagnostic freshness window, not a Running/Stopped determination. A job can still be running with `NotRecentlyModified`.
- Parser/state version changes invalidate older open manifests so timestamps and full source paths are rebuilt with current extraction rules. Already finalized COBs are left alone by design; run `run.cmd PROD --mode inventory --date YYYYMMDD --force` and then `run.cmd PROD --mode enrich --date YYYYMMDD --force` to rebuild a specific older report.

## Error handling and limitations

- The analyzer parses changed files **streamingly**, one line at a time; no full-file loading. Each log is opened in read-only mode, the initial file length is recorded from the open handle, and parsing stops at that length even if the writer appends meanwhile. It writes one CSV row per `.log` file, including jobs with no parseable timestamps (time columns empty).
- Each modified COB report is written to a temporary CSV in its destination folder, then **atomically replaced** before atomically updating its manifest. A crash after CSV publication but before manifest publication causes a safe reparse next time. Atomicity is per report/state file, not across all COB dates.
- Files and directories directly under `Logs` that are not valid `YYYYMMDD` COB folders are ignored without traversal. An unreadable log **still appears in an existing metadata inventory** as `Pending`/`Stale` if its metadata can be listed; enrichment retains that row and retries later, preventing COB finalization. A new log first discovered by enrichment (without prior inventory) may not appear until it can be read. An append during a scan is supported as a bounded snapshot: new bytes are picked up on the next run without rereading the file twice in the same run. Truncation, in-place rewrite, or a replaced file detected mid-read results in a deferred row, not an inconsistent new result. Unterminated tail lines of recently modified logs are ignored until completed. A run with skips returns exit code `2`; exit `1` indicates fatal input/configuration failure. A traversal failure on a network share prevents publication of the affected COB.
- No source files are edited, locked, renamed, deleted, or permission-changed; symlinked files and directories are skipped. Source and output roots may not overlap. Logs with reversed timestamps have an empty duration rather than a negative execution time.
- Restarts are **heuristic**: the repeated first `INFO` text is treated as a new execution. For products where that string is repeated for non-restart reasons, this can overcount. No special marker for restart has been confirmed yet.
- Logs under accessible UNC shares may change during a scan; file signature checks reduce inconsistent reads but **cannot** make an atomic snapshot of a whole SMB tree. Timestamp metadata can be coarse or stale on unusual filesystems. A temporarily missing entire COB directory is not discovered; existing historical CSVs are not automatically deleted. Files renamed during scanning may be counted as removed and added.
- `last_error` can contain confidential internal data. **Keep both CSVs and `.state` manifests on approved internal storage; both may include original error text.** Ensure storage ACLs and retention/deletion policies cover output and backups. Only output summaries (counts and output path) are printed to the console, not error messages. Filename/message fields are protected against CSV formula injection when opened in spreadsheets.
- `job_status=Unknown` before enrichment and `Completed` after enrichment are **not** execution truth; this field must not be used for operational monitoring. `activity_status` represents file activity only. An application may buffer logging for hours, keep appending after job completion, or finish without any terminal line. A definitive Running/Completed/Failed status requires a scheduler API or verified job-specific termination markers.

## Tests

```cmd
python -m unittest discover -s tools/log_analyzer/tests -v
```

For an unattended run, call `analyze.py --env <ENV> --mode inventory` (default) and, when needed, `analyze.py --env <ENV> --mode enrich` (optionally `--date YYYYMMDD`, `--force`, `--output-dir PATH`, or `--delimiter ";"`).

Tests generate temporary logs in a fake Logs tree and do not require company-network access, web-app dependencies or the actual bank log files.
