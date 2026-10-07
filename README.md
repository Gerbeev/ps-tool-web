# ps-tool-web


## Standalone log analyzer

`tools/log_analyzer/` contains an independent Python CLI to recursively parse environment-specific job logs into CSV, including execution duration, restarts, WARN/ERROR counts, and the last error line. On Windows, double-click `tools/log_analyzer/1-setup.cmd` and then `tools/log_analyzer/2-start.cmd` for the interactive console menu (`1` select environment, `9` Settings, `0` Exit). Per-machine paths are saved to ignored `config.local.json`, leaving `config.json` as the portable template. See [tools/log_analyzer/README.md](tools/log_analyzer/README.md). No web-app startup or adapter connection is required.

## Canonical 2,500-job mock dataset

Until workstation connectors are wired, local mock mode uses one healthy environment-neutral reference file: `data/mock/reference_topology_2500.jsonl`. It contains exactly 2,500 hierarchical jobs across 25 synthetic four-digit business groups. AutoSys U1 is the default healthy reference projection. Process Scheduler U5 is materialized from the same source and receives a deterministic migration-problem overlay from `data/mock/u1_to_u5_migration_overlay.jsonl` (missing, failed, long-running, activated/waiting, on-ice/cancelled, slow-success execution-time regressions, timing and selected definition/dependency drift). Only AutoSys U1 and Process Scheduler U5 are enabled by default for Snapshots/Browse/Compare. See `docs/mock-reference-data.md`.

## Portable Git checkout (mock mode)

The committed project must include `data/mock/reference_topology_2500.jsonl`,
`data/mock/u1_to_u5_migration_overlay.jsonl`, all of `config/`, `examples/`,
`app/static/`, `app/templates/`, `.env.example`, and the Windows startup scripts.
The root `.gitignore` **does not ignore `data/`**; only generated state under
`data/runtime/` and the local `data/search.db*` SQLite index is ignored.

After cloning on another machine, run `setup-env.cmd`, then `start-server.cmd`
(or install `requirements.txt`, copy `.env.example` to `.env`, and launch Uvicorn).
The mock dataset is available immediately, with no generation or download step.
Keep `.env`, local DB indexes, and captured scheduler snapshots out of Git.

**When committing to an existing repository**, stage **all project code as well as
fixtures**. In particular `app/time_utils.py` is required by `app/models.py`; a checkout
missing that file fails with `ModuleNotFoundError: No module named 'app.time_utils'`.
The previous ZIP already included it, but it must also be committed to Git:

```bash
git add -A
git status --short
git ls-files --cached app/time_utils.py data/mock/reference_topology_2500.jsonl data/mock/u1_to_u5_migration_overlay.jsonl
git commit -m "Make project portable with complete mock assets and Python bootstrap"
```

Check the staged list before committing, particularly if you have local changes.
Do not commit `.env` or runtime snapshots; both remain ignored.

## Quick Start on Windows

From the project folder:

```cmd
setup-env.cmd
start-server.cmd
```

`setup-env.cmd` uses `python` first (Python 3.11+), falling back to `py -3` only
when needed. The Windows `py` launcher is **not required**. It creates `.venv`,
installs dependencies and creates `.env` from `.env.example` when needed.
The installer and server run a checkout/import preflight that detects missing
modules such as `app/time_utils.py`, templates, config files and mock fixtures.

To verify a checkout manually before installing dependencies:

```cmd
python -m scripts.verify_checkout --source
```

After installing dependencies:

```cmd
.venv\Scripts\python.exe -m scripts.verify_checkout --runtime
```

`start-server.cmd` starts the server. If this application's Uvicorn server is already listening on the configured port, the script stops it and starts a fresh instance. If another application owns the port, the script refuses to terminate it and exits with an error.

To open the application in your default browser:

```cmd
open-app.cmd
```

By default the application is available at `http://127.0.0.1:8000/`. The scripts read `PS_TOOL_WEB_HOST`, `PS_TOOL_WEB_PORT`, and reload settings from `.env`.

`ps-tool-web` is a web-based analysis and comparison tool for **CA AutoSys** and the internal **Process Scheduler** used by Risk Analytics workloads.

Its primary purpose is to make scheduler migration and operational validation easier by providing a single UI where users can inspect scheduler topologies, compare equivalent jobs across environments or scheduler platforms, and identify behavioral or configuration differences that may affect migration correctness.

## Purpose

The application is designed to support the transition of workloads from AutoSys to Process Scheduler and to provide a consistent way to validate that jobs migrated between the two systems remain functionally equivalent.

It helps answer questions such as:

- Does a corresponding Process Scheduler job exist for every expected AutoSys job?
- Are migrated jobs running with the same effective status and timing characteristics?
- Are important AutoSys/JIL configuration parameters preserved in the target scheduler?
- Are commands, dependencies, schedules, file-watch configuration, ownership, logging, alarms, retries, and runtime values equivalent?
- Which jobs exist only on one side of a comparison?
- Where in a topology does a specific job belong, and what are its runtime details?

The tool can also be used independently of migration work as a scheduler topology browser and job investigation interface.

## What the Application Does

`ps-tool-web` retrieves scheduler topology snapshots through a common adapter interface and normalizes them into a shared domain model. This allows AutoSys and Process Scheduler data to be browsed and compared through the same UI even though the source systems expose different native concepts and schemas.

The application currently supports four main workflows:

### Snapshots

The **Snapshots** view is the single ingress point for external scheduler data. It is the only UI workflow allowed to call scheduler adapters or the workstation bridge.

Users can:

- Select an enabled scheduler environment.
- Generate an AutoSys snapshot for the previous local calendar day (COB = today - 1 day).
- For Process Scheduler, load the environment's topology list through the bridge, select one topology, and generate a snapshot for it.
- Keep multiple immutable snapshots for the same environment/topology across different captures.
- See the generated snapshot catalog, including human-readable snapshot name, capture time, source scope, job/dependency counts, and snapshot ID.
- Delete generated snapshots from the catalog when they are no longer needed.

Every successful capture is validated and stored under `SNAPSHOT_DIR` (default `data/runtime/snapshots`). A failed capture does not modify existing snapshots. Snapshot names are generated as `ENV-AutoSys_YYYY-MM-DD_HH-MM-SS` or `ENV-ProcessScheduler_YYYY-MM-DD_TOPOLOGY`; the payload itself remains keyed by immutable UUID. Deleting a snapshot removes its catalog record, payload, and local search-index rows without contacting a scheduler source.

### Browse

The **Browse** view never contacts AutoSys, Process Scheduler, adapters, or the bridge. It only loads a snapshot that already exists in the local snapshot catalog.

Users can:

- Select an environment.
- Select one previously generated snapshot for that environment.
- Navigate job/box hierarchy using a lazily loaded tree.
- Search jobs in the loaded snapshot.
- Filter jobs by status.
- Open detailed job information without leaving the topology view.
- Inspect runtime and scheduler-specific attributes such as status, start/end time, machine, command, log paths, and AutoSys reference fields.

### Compare

The **Compare** view compares two previously generated immutable snapshots side by side. It does not refresh or fetch scheduler data. The two sides may represent different environments, different scheduler technologies, different capture times, or any combination of those.

The comparison engine:

- Matches equivalent jobs using configured identity mappings and normalization rules.
- Detects and isolates ambiguous identity mappings instead of silently selecting a job.
- Detects jobs present only on the left or right side.
- Separately compares topology containment and real execution dependencies.
- Detects normalized status mismatches.
- Compares configured AutoSys/JIL and runtime parameters.
- Distinguishes a real mismatch from an unsupported, unknown, or not-applicable adapter field.
- Detects timing differences using a configurable threshold.
- Preserves optional field-level provenance for explaining normalized values.
- Produces comparison coverage and mismatch summaries.
- Supports side-by-side topology inspection and individual job details.
- Provides filtering, search, and CSV export from the frozen comparison session.

This workflow is intended to highlight migration gaps quickly while guaranteeing that both sides remain stable throughout an analysis session.

### Settings

The **Settings** view manages scheduler-specific environment definitions used by Snapshots, Browse, and Compare. Process Scheduler and AutoSys are configured on separate tabs and persisted to separate YAML files.

Each scheduler tab exposes only the operator-facing fields needed for connection management:

- Environment code.
- Host.
- Description.
- Enabled state, including a header checkbox to enable or disable every environment in that scheduler table.

Display labels are generated dynamically as `ENV (Description)` and are not duplicated in YAML. The scheduler type comes from the scheduler-specific config file. Internal adapter-selection metadata may be supplied by a bank deployment, but it is intentionally not exposed as an editable Settings column.

## Functional Features

### Unified Scheduler Model

AutoSys and Process Scheduler jobs are converted into a common `SnapshotJob` / `TopologySnapshot` model. This provides one comparison and UI layer regardless of the source scheduler.

### Job Identity Matching

The application assigns logical identities to jobs so that differently named AutoSys and Process Scheduler jobs can still be paired correctly.

Matching can use:

- Explicit mappings from `config/identity_map.yaml`.
- Structured scheduler naming rules from `config/job_naming_rules.yaml`.
- Normalized job names.
- Name-based fallback matching.

The naming convention is modeled generically as `common prefix -> 4-digit business code -> environment token -> job-specific name`. For cross-environment comparison, the canonical identity retains the business code and job-specific name while excluding the environment token and globally shared prefix. Concrete business codes, environment values, job names, and the literal shared prefix are intentionally not stored in the rule definition.

Each match carries a confidence classification such as mapped, normalized, name-only, or unmatched.

### AutoSys Migration-Parity Comparison

The comparison model contains an AutoSys reference representation for the AutoSys side and an AutoSys-equivalent projection for Process Scheduler jobs. The Process Scheduler adapter builds that projection from the Process Scheduler endpoint response without losing useful native endpoint fields.

The AutoSys model is aligned with high-value Broadcom CMD/FW/BOX semantics and preserves unknown JIL attributes so additional job types can be enabled without silently losing source data. Comparison uses semantic normalization for equivalent JIL forms rather than raw string equality.

The parameters used for parity checks are configurable in `config/autosys_compare_parameters.yaml` and currently include fields such as:

- Job type and machine.
- Box membership.
- Command or watched file.
- Conditions and date conditions.
- Start times and start minutes.
- Days of week, run calendar, and timezone.
- Standard output and error files.
- Owner, permission, group, and application metadata.
- Failure/runtime alarms, retries, notification mode/template policy, and auto-delete behavior.
- Resolved command, exit code, and actual start/end times.
- Normalized cross-scheduler status is compared separately from native status strings.
- Actual start and end times.

Timing comparison uses a configurable tolerance instead of requiring exact timestamps. Completed jobs also expose `Exec Time` as `actual_end - actual_start` in `HH:MM:SS`; Compare shows left/right execution time plus signed `Exec Δ (R−L)` and flags duration regressions using a separate configurable execution-time threshold.

### Topology and Dependency Navigation

Scheduler jobs are organized as hierarchical topology trees. Child nodes are loaded on demand, which keeps navigation practical for larger job structures rather than rendering the entire hierarchy at once.

Hierarchy and execution dependencies are modeled separately: `parent_uid` / tree nodes represent containment, while `DependencyEdge` represents a real runtime prerequisite. Compare checks dependency predecessor parity for matched jobs in addition to JIL/runtime fields.

### Search

Loaded scheduler snapshots are indexed using SQLite Full-Text Search (FTS), allowing users to locate jobs quickly from the UI or through the search API.

### Status Filtering

Browse and comparison views support status-oriented filtering so that users can focus on failed, running, pending, inactive, or otherwise relevant jobs and mismatches.

### Job Detail Inspection

Individual jobs expose normalized runtime information together with scheduler-specific reference data, including available log paths and execution metadata.

### CSV Export

Comparison sessions can export:

- Left-side topology data.
- Right-side topology data.
- Comparison/difference results.

This allows findings to be reviewed outside the UI or attached to migration and validation workflows.

### Immutable Snapshot Catalog

Snapshots are durable, independent records rather than a single mutable left/right pair. Each successful generation creates a new `snapshot_id`, gzip-compressed payload, checksum, and catalog entry under `SNAPSHOT_DIR`. Existing snapshots are never overwritten by a new capture.

The data flow is intentionally one-way:

```text
Snapshots tab -> adapter / scheduler-bridge/v1 -> validate -> snapshot catalog
Browse        -> snapshot catalog only
Compare       -> snapshot catalog only
Search/export -> loaded snapshot sessions/catalog only
```

For AutoSys, generation fixes the source context to the previous local calendar day (COB = today - 1 day). For Process Scheduler, the Snapshots view first requests available topologies through `list_roots`, then fetches only the selected topology. Browse and Compare expose neither business-date nor topology source controls because those choices are already frozen into the selected snapshot.

This separation is the main source-isolation contract: replacing or refactoring Browse/Compare must not introduce adapter or bridge calls. See `docs/snapshots.md`.

## Intended Users

The tool is primarily intended for:

- Engineers migrating Risk Analytics workloads from AutoSys to Process Scheduler.
- Developers validating scheduler definitions after migration changes.
- Support and operations engineers investigating differences between environments.
- Teams reviewing scheduler topology, execution state, or job-level configuration without switching between multiple scheduler interfaces.

## Current Implementation Status

The repository contains a working FastAPI web application with **mock AutoSys and Process Scheduler adapters** and sample scheduler data.

The comparison engine is intentionally separated from bank connectivity. Real scheduler integration is out-of-process through the frozen `scheduler-bridge/v1` contract: `ExternalBridgeAdapter` invokes fixed scripts under `workstation_connectors/`, while the bank-local scripts call the existing AutoSys and Process Scheduler tools. Those scripts never import `app` and are git-ignored.

The engine includes `TopologySnapshotBuilder`, strict adapter capability declarations, normalized-snapshot validation, field-level comparison provenance, identity-conflict protection, and a reusable adapter contract check. The bridge translator converts the stable external v1 DTO into the current internal domain model, so the web engine can evolve without forcing workstation connector rewrites.

When `USE_MOCK_ADAPTERS=true`, the application runs without corporate scheduler access. On the bank workstation set it to `false` and provide `workstation_connectors/autosys_connector.py` and `workstation_connectors/process_scheduler_connector.py`. Credentials/tokens/certificates stay inside approved bank secret mechanisms and are never committed or passed in environment YAML.

On a Windows workstation, preferably keep connectors in a persistent folder outside the replaceable web-project directory. Run `setup-workstation-connectors.cmd <persistent-directory>` once; it copies the frozen v1 templates without overwriting existing connector files, then set `PS_TOOL_CONNECTOR_DIR` to that directory in `.env`.

## Architecture Overview

```text
Browser
  |
  +-- Snapshots ----------------------------------------------+
  |      |                                                    |
  |      v                                                    |
  |   SnapshotGenerationService                               |
  |      |                                                    |
  |      v                                                    |
  |   SchedulerAdapter -> ExternalBridgeAdapter               |
  |      |              scheduler-bridge/v1 JSON              |
  |      +------------> workstation connector scripts --------+--> bank scheduler tools/APIs
  |
  |                         validated immutable snapshot
  |                                      |
  |                                      v
  +-- Browse ----------------------> SnapshotCatalog <---------------- Compare
  |                                      |                              |
  +-- Search / Export -------------------+------------------------------+
```

`Snapshots` is the only web route group that reads an external scheduler. Browse, Compare, Search, and Export operate on persisted snapshots or in-memory sessions created from them. The portable application integrates with bank-local systems only through the fixed workstation connector scripts and the frozen `scheduler-bridge/v1` contract.

## Configuration

| File | Purpose |
|---|---|
| `config/process_scheduler_environments.yaml` | Process Scheduler environment/host catalog |
| `config/autosys_environments.yaml` | AutoSys environment/host catalog |
| `config/identity_map.yaml` | AutoSys ↔ Process Scheduler identity mappings and normalization rules |
| `config/job_naming_rules.yaml` | Generic scheduler job-name structure and cross-environment identity rules |
| `config/autosys_compare_parameters.yaml` | JIL/runtime parameters and timing threshold used for parity comparison |
| `.env` | Runtime settings such as host, port, cache behavior, mock mode, and workstation connector path/limits |
| `.env.example` | Example runtime configuration |

## Main HTTP Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/snapshots` | Generate and list immutable scheduler snapshots |
| `GET` | `/api/snapshots/source-form` | Load source-specific generation controls/topologies |
| `POST` | `/api/snapshots/generate` | Fetch, validate, and persist one source snapshot |
| `GET` | `/browse` | Browse a generated snapshot |
| `POST` | `/api/browse/load` | Load a generated snapshot from the local catalog |
| `GET` | `/compare` | Open the generated-snapshot comparison workflow |
| `POST` | `/api/compare` | Compare two generated snapshot IDs |
| `GET` | `/api/search` | Search jobs in loaded snapshots |
| `GET` | `/api/export/left.csv` | Export the left comparison snapshot |
| `GET` | `/api/export/right.csv` | Export the right comparison snapshot |
| `GET` | `/api/export/comparison.csv` | Export comparison differences |
| `GET` | `/settings` | Manage scheduler environments |
| `GET` | `/health` | Application liveness check |

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

On Windows, use `setup-env.cmd`, `start-server.cmd`, and `open-app.cmd` as described in **Quick Start on Windows** at the top of this README.

Open `http://127.0.0.1:8000/` after the server starts.

## Tests

```bash
python -m pytest
```

The test suite covers browse, comparison, AutoSys semantics, environment configuration, parameter comparison, dependency/topology parity, partial adapter coverage, identity conflicts, snapshot validation, CSV export, filtering, root-scope, and scalability behaviors.

Real adapters can be self-checked with:

```bash
python -m app.adapters.check --environment <env> --scheduler <autosys|process_scheduler> --as-of <YYYY-MM-DD>
```

See `docs/adapter-integration-guide.md` and `docs/workstation-connector-protocol-v1.md` for the fixed bank-workstation handoff contract.

## Project Structure

```text
app/
  adapters/        Engine adapter interface, mock adapters, bridge v1 translator/client
  routes/          FastAPI Snapshots, Browse, Compare, Search, Export and Settings routes
  search/          SQLite FTS search implementation
  services/        Snapshot catalog/generation, comparison, identity, topology and export logic
  templates/       Jinja2/HTMX web UI
  models.py        Shared scheduler and comparison domain models

config/            Environment, identity and comparison configuration
examples/          Sample payloads and workstation connector templates
workstation_connectors/  Git-ignored bank-local connector implementations
docs/              Supporting implementation and field-mapping documentation
contracts/         Frozen machine-readable scheduler-bridge/v1 schemas
tests/             Automated test suite
data/              Runtime/search data and UI preview assets
```

## Design Intent

The central design goal is to keep **scheduler connectivity confined to snapshot generation**. Once a source system is represented as an immutable normalized snapshot, Browse, Compare, search, export, filtering, and UI behavior remain scheduler-independent and cannot accidentally change underneath an analysis.

This makes `ps-tool-web` suitable as a focused validation layer during scheduler migration while also providing a foundation for connecting real AutoSys and Process Scheduler data sources later.
