# ps-tool-web


## Canonical 2,500-job mock dataset

Until real scheduler endpoint adapters are wired, local mock mode uses one environment-neutral reference file: `data/mock/reference_topology_2500.jsonl`. It contains exactly 2,500 hierarchical scheduler nodes across 25 synthetic four-digit business groups. U5, P1 and other environments are materialized from this same file by changing only the embedded environment token in native job names. See `docs/mock-reference-data.md`.

## Quick Start on Windows

From the project folder:

```cmd
setup-env.cmd
start-server.cmd
```

`setup-env.cmd` creates `.venv`, installs dependencies, and creates `.env` from `.env.example` when needed. It normally needs to be run only once.

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

The application currently supports three main workflows:

### Browse

The **Browse** view loads a single scheduler environment and presents its jobs as a hierarchical topology.

Users can:

- Select an environment and its configured scheduler type.
- Select a business date or topology context.
- Navigate job/box hierarchy using a lazily loaded tree.
- Search jobs in the loaded snapshot.
- Filter jobs by status.
- Open detailed job information without leaving the topology view.
- Inspect runtime and scheduler-specific attributes such as status, start/end time, machine, command, log paths, and AutoSys reference fields.

### Compare

The **Compare** view compares two scheduler contexts side by side. The two sides may represent different environments, different scheduler technologies, or both.

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
- Provides filtering and search for large comparison results.

This workflow is intended to highlight migration gaps quickly rather than requiring operators to inspect both schedulers manually.

### Settings

The **Settings** view manages scheduler-specific environment definitions used by Browse and Compare. Process Scheduler and AutoSys are configured on separate tabs and persisted to separate YAML files.

Environment configuration includes:

- Environment identifier and display name.
- Scheduler type (`autosys` or `process_scheduler`).
- Host information.
- Connector profile metadata.

The configuration is persisted in YAML and can be extended for real scheduler connectors.

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

Timing comparison uses a configurable tolerance instead of requiring exact timestamps.

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

### Snapshot Caching and Session State

Fetched scheduler snapshots are cached and reused during a session to avoid unnecessary repeated retrieval. Browse and Compare maintain session-scoped state for subsequent tree, job-detail, search, and export requests.

## Intended Users

The tool is primarily intended for:

- Engineers migrating Risk Analytics workloads from AutoSys to Process Scheduler.
- Developers validating scheduler definitions after migration changes.
- Support and operations engineers investigating differences between environments.
- Teams reviewing scheduler topology, execution state, or job-level configuration without switching between multiple scheduler interfaces.

## Current Implementation Status

The repository contains a working FastAPI web application with **mock AutoSys and Process Scheduler adapters** and sample scheduler data.

The adapter abstraction is intentionally separated from the comparison logic. Real scheduler integrations are added by implementing `SchedulerAdapter` and explicitly registering trusted factories in `app/adapters/site.py`; source-specific behavior should not be added to the comparison service.

The engine includes `TopologySnapshotBuilder`, strict adapter capability declarations, normalized-snapshot validation, field-level comparison provenance, identity-conflict protection, and a reusable adapter contract check. This allows the complete engine to be developed with synthetic data and the bank-internal AutoSys and Process Scheduler endpoint adapters to be added later.

When `USE_MOCK_ADAPTERS=true`, the application can be run locally without access to corporate scheduler systems. When real endpoint adapters are introduced, credentials/tokens/certificates should be supplied through approved bank secret management rather than committed configuration files. Process Scheduler's internal Cosmos DB access remains behind its service endpoint and is not accessed by this application.

## Architecture Overview

```text
Browser
  |
  v
FastAPI + Jinja2 + HTMX UI
  |
  +-- Browse / Compare / Search / Export / Settings routes
  |
  +-- Comparison, identity, topology and export services
  |
  +-- Shared scheduler domain model
  |
  +-- SchedulerAdapter interface
        |
        +-- AutoSys endpoint adapter ----------> bank AutoSys endpoint
        +-- Process Scheduler endpoint adapter -> bank Process Scheduler endpoint -> internal Cosmos DB
```

The application integrates only with scheduler service endpoints. Process Scheduler storage (including Cosmos DB) is intentionally opaque to this tool. The architecture keeps source-specific transport/DTO mapping behind adapters while the rest of the application works with normalized snapshots. Missing connector coverage is explicit: a real adapter should enable strict parameter support and declare each field as `supported`, `unsupported`, `unknown`, or `not_applicable`.

## Configuration

| File | Purpose |
|---|---|
| `config/process_scheduler_environments.yaml` | Process Scheduler environment/host catalog and connector profiles |
| `config/autosys_environments.yaml` | AutoSys environment/host catalog and connector profiles |
| `config/identity_map.yaml` | AutoSys ↔ Process Scheduler identity mappings and normalization rules |
| `config/job_naming_rules.yaml` | Generic scheduler job-name structure and cross-environment identity rules |
| `config/autosys_compare_parameters.yaml` | JIL/runtime parameters and timing threshold used for parity comparison |
| `.env` | Runtime settings such as host, port, cache behavior, mock-adapter mode, and paths |
| `.env.example` | Example runtime configuration |

## Main HTTP Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/browse` | Browse a scheduler topology |
| `POST` | `/api/browse/load` | Load a topology snapshot |
| `GET` | `/compare` | Open the scheduler comparison workflow |
| `POST` | `/api/compare` | Run a comparison |
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

See `docs/adapter-integration-guide.md` for the bank-side agent handoff contract.

## Project Structure

```text
app/
  adapters/        Adapter contract, registry, snapshot builder, mock adapters, integration hook
  routes/          FastAPI Browse, Compare, Search, Export and Settings routes
  search/          SQLite FTS search implementation
  services/        Comparison, identity, topology, caching and export logic
  templates/       Jinja2/HTMX web UI
  models.py        Shared scheduler and comparison domain models

config/            Environment, identity and comparison configuration
examples/          Sample AutoSys and Process Scheduler payloads
docs/              Supporting implementation and field-mapping documentation
tests/             Automated test suite
data/              Runtime/search data and UI preview assets
```

## Design Intent

The central design goal is to keep **scheduler connectivity separate from migration validation logic**. Once both source systems are represented as normalized topology snapshots, comparison, search, export, filtering, and UI behavior remain scheduler-independent.

This makes `ps-tool-web` suitable as a focused validation layer during scheduler migration while also providing a foundation for connecting real AutoSys and Process Scheduler data sources later.
