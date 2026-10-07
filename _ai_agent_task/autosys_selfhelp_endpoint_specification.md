# AutoSys "selfhelp" Web Endpoint Specification

Spec for building, from scratch, a connector that pulls job status and JIL definitions from the
AutoSys "selfhelp" web endpoint.

## 1. Transport

- Plain HTTPS, no .NET bridge needed (unlike Process Scheduler).
- Base URL (real, current): `https://autosys.ldn.swissbank.com/selfhelp/tool.cgi`
- Method: `GET`, query-string params only.
- TLS cert is internal/self-signed → client must disable certificate verification.
- Auth: Windows Integrated Auth (SSPI/Kerberos), negotiated transparently. Try SSPI first, then
  Kerberos (`mutual_authentication=False`), otherwise fall back to anonymous (works if the
  endpoint allows it / IP-allowlisted).
- Defaults: `timeout_seconds: 60`, `verify_ssl: false`.

## 2. Query parameters

| Param | Meaning | Example |
|---|---|---|
| `t` | report type: `job` (status list), `jil` (full job definition), `jobp` (job properties, seen in the wild, not currently parsed by this tool) | `t=jil` |
| `i` | AutoSys instance code | `i=IUT` |
| `q` | job/box name or `%`-wildcard pattern | `q=IB_CT_CVA_1109_U1_%25` (`%25` = URL-encoded `%`) |

Real configured instances: `IUT` (AutoSys UAT) and `IL2` (AutoSys PROD). The instance is tied to
the environment tier, not selected via `q` — all `U`-prefixed environments (e.g. `U1`, `U5`, job
names like `IB_CT_CVA_1109_U1_...`) are UAT and use `i=IUT`. PROD environments use their own
env-code segment instead (e.g. `P1` for `IB_CT_CVA_1109_P1_...`) and use `i=IL2`; a `q` wildcard
with no env segment (e.g. `IB_CT_CVA_1109_%25`) matches jobs across all PROD environments on
that instance.

Real example requests (UAT, environment `U1`):
```
GET https://autosys.ldn.swissbank.com/selfhelp/tool.cgi?t=job&i=IUT&q=IB_CT_CVA_1109_U1_%25
GET https://autosys.ldn.swissbank.com/selfhelp/tool.cgi?t=jil&i=IUT&q=IB_CT_CVA_1109_U1_DP_ADP_Accounts_Load
GET https://autosys.ldn.swissbank.com/selfhelp/tool.cgi?t=jobp&i=IUT&q=IB_CT_CVA_1109_U1_DP_ADP_Accounts_Load
```

Real example requests (PROD, environment `P1`):
```
GET https://autosys.ldn.swissbank.com/selfhelp/tool.cgi?t=job&i=IL2&q=IB_CT_CVA_1109_%25
GET https://autosys.ldn.swissbank.com/selfhelp/tool.cgi?t=jil&i=IL2&q=IB_CT_CVA_1109_P1_DP_Counterparty_MPR_Load
```



## 3. Response shape

HTML page. The actual content is plain text (status table or JIL) inside the HTML, extracted by:
1. Parse with Python's stdlib `html.parser.HTMLParser` (no external HTML lib needed).
2. Collect text inside `<pre>...</pre>` tags.
3. If no non-blank `<pre>` text was found, fall back to all page text (handles pages that don't
   wrap output in `<pre>`).

## 4. Operation: `t=job` — job/box status search (list)

Returns a fixed-width plain-text table, one job/box per line (same rendering as CLI `autorep -J`),
wrapped inside a `<pre>...</pre>` tag in the HTML response (see §3 for extraction). No fixed
column layout is assumed by the parser — only name-prefix heuristics:

- Skip blank lines and separator lines (`^[-_=\s]+$`).
- First whitespace-delimited token must match `[A-Za-z0-9_.\-]{3,}` to count as a name.
- Skip header-like first tokens: `job`, `job_name`, `jobname`, `box`, `status` (case-insensitive).
- De-duplicate by name, preserve first occurrence's full raw line.

Result: list of `(name, raw_line)` pairs. Empty result ⇒ "no jobs matched pattern".

### 4.1 Real example (instance `IL2`, `q=IB_CT_CVA_1109_P1_%25`)

```
Job Name                                                          Last Start           Last End             ST/Ex Run/Ntry Pri/Xit TimeZone
----------------------------------------------------------------- -------------------- -------------------- ----- -------- -------
IB_CT_CVA_1109_P1_Admin_Box                                        10/06/2026 23:32:50  10/06/2026 23:48:48  SU    38912674/1 0 (London)
 IB_CT_CVA_1109_P1_Admin_HouseKeeping_RAIF_B3                        10/06/2026 23:32:52  10/06/2026 23:47:13  SU    38912674/1 0 (London)
 IB_CT_CVA_1109_P1_Admin_HouseKeeping_RAIF_CVA                       10/06/2026 23:32:52  10/06/2026 23:48:48  SU    38912674/1 0 (London)
 IB_CT_CVA_1109_P1_Admin_Jils                                       10/06/2026 23:32:51  10/06/2026 23:33:25  SU    38912674/1 0 (London)
 IB_CT_CVA_1109_P1_Admin_HouseKeeping_BT_RMT_Reports                 10/06/2026 23:32:52  10/06/2026 23:32:55  SU    38912674/1 0 (London)
 IB_CT_CVA_1109_P1_Admin_RRS_CreatePartitions                        10/06/2026 23:32:52  10/06/2026 23:33:34  SU    38912674/1 0 (London)
IB_CT_CVA_1109_P1_Deployment_Checker                               09/11/2026 13:26:10  09/11/2026 13:31:14  OI    38289163/5 0 (London)
```

Columns (header + `-----` separator row — both skipped by the parser, see above): `Job Name`,
`Last Start`, `Last End`, `ST/Ex` (status code / exit code), `Run/Ntry` (run number / try id),
`Pri/Xit` (priority / exit code), `TimeZone` (in parens). Jobs belonging to a box are indented
with a **leading space** under their parent box's row — the parser's name-token match still
works on the indented line since it splits on whitespace first. `ST` status codes seen: `SU`
(success), `OI` (on ice), others follow the same two-letter convention as `autorep -J` (`RU`
running, `FA` failed, `TE` terminated, etc.) — treat unrecognized codes as opaque strings, don't
hardcode an exhaustive enum.

## 5. Operation: `t=jil` — full JIL definition (describe one job, exact name, no wildcard)

Returns the full native AutoSys JIL (Job Information Language) text block for exactly one job.
Validity check: response text must contain `insert_job:`, else treated as "not found".

### 5.1 Real example (instance `IUT`, job `IB_CT_CVA_1109_U1_DP_ADP_Accounts_Load`)

```
/* ----------------- IB_CT_CVA_1109_U1_DP_ADP_Accounts_Load ----------------- */

insert_job: IB_CT_CVA_1109_U1_DP_ADP_Accounts_Load   job_type: CMD
box_name: IB_CT_CVA_1109_U1_DP_ADP_Box
command: $$(1109_GV_U1_DP_Batch_TE)\RA.DataPlatform.TransformationEngine.Host.exe B /ES=$$(1109_GV_U1_Config)$$(1109_GV_U1_DP_ES_I) -m=RA.DataPlatform.Inventory.Modules.adp -c=adp-account-batch-datasource -CobDate=$$(1109_GV_U1_CVA_Date) LatestOnly=True
machine: 1109_VM_CVA_Win_U1_Prim_5
owner: svc_ra_uat@ubsprod
permission: mx,gx
date_conditions: 0
condition: s(IB_CT_CVA_1109_U1_DP_ADP_ClearedPositions_Load) & s(IB_CT_CVA_1109_U1_DP_GMI_Accounts_Box)
description: "Rerun=0;117;#IBCT_Autosys;DL-CVA-IT-BATCH-ERROR"
std_out_file: "$$(1109_GV_U1_CVA_Logs)\$$(1109_GV_U1_CVA_Date)\DataPlatform\ADP\Accounts\%AUTO_JOB_NAME%.log"
std_err_file: "$$(1109_GV_U1_CVA_Logs)\$$(1109_GV_U1_CVA_Date)\DataPlatform\ADP\Accounts\%AUTO_JOB_NAME%.log"
max_run_alarm: 17
alarm_if_fail: 1
profile: "1109_CVA_IUT"
alarm_if_terminated: 1
timezone: London
group: DP01
application: 1109_APP_AT16831
```

### 5.2 JIL field reference (as observed)

| Field | Meaning |
|---|---|
| `insert_job` | job name being defined (matches the `q=` query) |
| `job_type` | `CMD` (command), `BOX` (container), `FW` (file watcher), etc. |
| `box_name` | parent box this job belongs to (schedule/condition inheritance) |
| `command` | full command line executed, incl. `$$(...)` AutoSys global variable substitutions |
| `machine` | execution agent/host alias the job runs on |
| `owner` | service account the job runs as |
| `permission` | ACL, e.g. `mx,gx` (modify/execute by group) |
| `date_conditions` | `0`/`1` — whether `days_of_week`/`run_calendar` style scheduling is active |
| `condition` | dependency expression, e.g. `s(JOB)` = success of `JOB`; `&`/`\|` combine conditions |
| `description` | free text, here encodes rerun policy + alert routing (`#IBCT_Autosys;DL-...` distro list) |
| `std_out_file` / `std_err_file` | log file path templates (`%AUTO_JOB_NAME%` macro expands to job name) |
| `max_run_alarm` | minutes before a "long-running" alarm fires |
| `alarm_if_fail` / `alarm_if_terminated` | `0`/`1` flags to raise alerts |
| `profile` | environment/profile script sourced before running the command |
| `timezone` | scheduling timezone for this job |
| `group` | logical grouping label |
| `application` | owning application code (billing/inventory tag) |

Box jobs (`job_type: BOX`) omit `command`/`machine` and instead define scheduling directly
(`start_times`, `run_calendar`, `days_of_week`, etc. — same JIL grammar, just different field set
for box vs. command job types).

## 6. How to get job info

1. `GET base_url` with params `{t, i, q}`, `timeout=60`, TLS verification disabled.
2. On HTTP/network failure, surface as a source error.
3. Extract text from `<pre>` tags in the HTML response (fallback: all page text).
4. For `t=job`: line-filter per §4 → list of job/box names.
5. For `t=jil`: return raw text as-is after confirming `"insert_job:" in text` — the raw text
   *is* the full job spec (command line, box, machine, condition, schedule); parse individual
   fields with `^<field>:\s*(.*)$` per line if needed, respecting quoted multi-token values.

## 7. Error semantics

| Situation | Behavior |
|---|---|
| HTTP/network failure | source error |
| `t=jil` response missing `insert_job:` | source error "job not found (no JIL text returned)" |
| `t=job` no matching lines | empty result, not an error |
