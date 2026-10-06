# Standalone Job Log Analyzer

Independent console application for exporting job-log metrics to CSV. **Python 3.11+ only; no pip packages, database, application server, or scheduler adapters required.**

## Windows quick start (interactive menu)

Open the `tools\log_analyzer` folder and double-click the CMD launchers in this order:

1. **`1-setup.cmd`** — finds an installed Python 3.11+ (`python` first, `py -3` fallback), validates the JSON config, and checks dependencies. This tool uses Python's standard library only, so there is nothing to install with pip.
2. **`2-start.cmd`** — opens the console menu. It also works without running setup first if Python is already installed.

You can also invoke `2-start.cmd` from an existing Command Prompt. The tool stays in the console until you select `0`.

```text
================================
       JOB LOG ANALYZER
================================
1. Select environment / Parse logs
9. Settings
0. Exit
Select:
```

**Option 1 — Parse logs**: select an environment by number or code, review its Logs root and CSV destination, and confirm `Start parsing? [y/N]`. Only `y` or `yes` triggers the scan. By default it recursively scans **all dated directories** and all nested `.log` files under the chosen root. When finished, it reports files processed/skipped and WARN/ERROR totals, then returns to the main menu.

**Option 9 — Settings**:

```text
1. Edit environment log path
2. Edit environment description
3. Add environment
4. Change log file encoding
0. Back
```

Settings are written atomically to **`config.local.json`**, which is intentionally ignored by Git. The portable example `config.json` is never modified. The menu and the direct CLI automatically use `config.local.json` when it exists; otherwise they read `config.json`. This lets each machine use its own local/UNC shares without committing machine-specific paths. You can still supply `--config` explicitly to the direct CLI.

**Option 0 — Exit**: closes the menu normally. Errors during a scan show an English message and return to the menu; an existing CSV is preserved if the scan fails before producing a report.

**Output**: `tools\log_analyzer\output\<ENV>_jobs.csv`. A successful subsequent scan of the same environment replaces its previous CSV. Output is local to this tool and contains potentially confidential log errors; keep it on approved storage.

## Configuration

The template `config.json` contains initial environments and their log roots:

```json
{
  "encoding": "utf-8-sig",
  "environments": {
    "PROD": {
      "logs_root": "\\\\ldnroot\\data\\IBCT\\CVA\\PROD\\Logs",
      "description": "Production log root shown in the screenshot"
    },
    "U5": {
      "logs_root": "",
      "description": "Set the real U5 Logs root"
    }
  }
}
```

`PROD` is populated from the screenshot; it is a Windows UNC path and only works with network access and appropriate permissions. `U5`, `U1`, and `P1` need local paths configured in menu option 9. You can also edit `config.local.json` manually. The `P1` token in a job filename does **not** prove the Logs root uses a `P1` folder; the screenshot shows it under `PROD`.

Paths are environment-specific and can point to local disks, mapped drives or UNC shares. Relative paths in custom config files resolve relative to that config file. Encoding may be changed (e.g. to `cp1252`) if the source logs are not UTF-8. The CLI reads source files only.

## Run from the project root

```cmd
python tools\log_analyzer\analyze.py --env PROD
python tools\log_analyzer\analyze.py --env PROD --date 20261002
python tools\log_analyzer\analyze.py --env U5 --output C:\Temp\u5-report.csv
```

Or, from the tool folder on Windows:

```cmd
run.cmd PROD
run.cmd PROD --date 20261002
```

No `.venv` or external installation is needed. `python` is preferred; the Windows CMD scripts fall back to `py -3` if necessary. `run.cmd` remains available for scripted/noninteractive use.

The default output is `tools/log_analyzer/output/<ENV>_jobs.csv`; generated output is ignored by Git. The tool recursively scans **all `*.log` files** under the selected Logs root and, unless `--date` is supplied, all available business-date directories.

Optional `--delimiter ";"` supports semicolon-separated output for regional spreadsheet settings. The CSV uses `utf-8-sig` so Excel can detect UTF-8 reliably.

## CSV columns

| Column | Calculation |
|---|---|
| `job_date` | Nearest ancestor folder in `YYYYMMDD` format beneath the configured Logs root, **not** the log timestamp; e.g. `20261002` |
| `job_name` | Log filename without `.log` (the native environment token remains intact) |
| `job_status` | Always `Completed` by request; no success/failure inference |
| `start_time` | First parseable log record timestamp |
| `end_time` | Last parseable log record timestamp |
| `duration` | Difference `end_time - start_time` as `HH:MM:SS`, with hours allowed above 24 |
| `restart_count` | Occurrences of the complete text following the first nonempty `INFO` record minus 1, minimum 0 |
| `warning_count` | Count of timestamped `WARN`/`WARNING` records |
| `error_count` | Count of timestamped `ERROR` records |
| `last_error` | Full last timestamped `ERROR` line (including timestamp, thread, and message) |

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

`job_date` is `20261002`, while start/end can legitimately be on `2026-10-05`. The directory identifies the business date, not necessarily the log's calendar date.

## Error handling and limitations

- The analyzer reads files **streamingly**, one line at a time; no full-file loading. It writes one CSV row per `.log` file, including jobs with no parseable timestamps (time columns empty).
- Output is written to a temporary CSV and **atomically replaced** only after at least one eligible log is processed. It will not destroy the previous report when the root is unavailable or no logs match.
- A log without a valid `YYYYMMDD` ancestor, or one that cannot be read, is skipped with a stderr message. A report with any skips returns exit code `2` rather than pretending it is complete. Exit `1` indicates fatal input/configuration failure.
- No source files are edited; symlinked files and directories are skipped. Logs with reversed timestamps have an empty duration rather than a negative execution time.
- Restarts are **heuristic**: the repeated first `INFO` text is treated as a new execution. For products where that string is repeated for non-restart reasons, this can overcount. No special marker for restart has been confirmed yet.
- Logs under accessible UNC shares may change during a scan; the report is a best-effort view of each file as read, not a synchronized snapshot of the entire share.
- `last_error` can contain confidential internal data. **Keep CSVs on approved internal storage.** Only output summaries (counts and output path) are printed to the console, not error messages. Filename/message fields are protected against CSV formula injection when opened in spreadsheets.

## Tests

```cmd
python -m unittest discover -s tools/log_analyzer/tests -v
```

For an unattended run, skip the interactive menu and call `analyze.py --env <ENV>` (optionally `--date YYYYMMDD`, `--output PATH`, or `--delimiter ";"`).

Tests generate temporary logs in a fake Logs tree and do not require company-network access, web-app dependencies or the actual bank log files.
