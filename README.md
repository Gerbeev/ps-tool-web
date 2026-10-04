# ps-tool-web

Web UI for **pairwise comparison** of CA AutoSys and internal Process Scheduler topologies (UBS Risk Analytics migration tool).

Phase 2 ships a runnable skeleton with **mock adapters**, HTMX compare UI, SQLite FTS search, and CSV export. Real Python connectors plug in via `SchedulerAdapter` implementations.

## Quick start

```bash
cd ps-tool-web
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

Default demo: **UAT AutoSys (left)** vs **Test Process Scheduler (right)**, business date `2026-10-02`, then **Compare**. Mock data includes:

- Status mismatch on recon job (failure vs success)
- Left-only legacy report job
- Right-only ad hoc / post-process jobs
- Timing deltas on several paired jobs
- AutoSys-reference parameter parity (`SnapshotJob.autosys`) — see `docs/autosys-compare-parameters.md`

Sample job payloads loaded by mock adapters: `examples/autosys_jobs.sample.yaml`, `examples/process_scheduler_jobs.sample.yaml`.

## Configuration

| File | Purpose |
|------|---------|
| `config/environments.yaml` | Environment ids and display names |
| `config/identity_map.yaml` | AutoSys ↔ PS name pairs and regex rules |
| `config/autosys_compare_parameters.yaml` | JIL/run attributes compared for migration parity |
| `.env` | Host/port, cache TTL, `USE_MOCK_ADAPTERS`, paths |

Secrets stay out of git; reference connector profiles in YAML and load credentials from env/vault in real adapters.

## Adapter extension points

1. Implement `SchedulerAdapter` in `app/adapters/base.py` (see spec §5.2).
2. Wrap existing modules (e.g. `connectors.autosys`, `connectors.process_scheduler`) in new classes under `app/adapters/`.
3. Update `get_adapter()` in `app/adapters/factory.py` to select real vs mock based on `USE_MOCK_ADAPTERS` and `connector_profile` from `environments.yaml`.
4. Map native statuses to `JobStatus` and populate `SnapshotJob` (with `AutoSysJobReference`) / `DependencyEdge` in `fetch_topology()`.

## API (selected)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Compare page |
| POST | `/api/compare` | Run comparison (HTMX partial) |
| GET | `/api/search?q=` | Job search (HTML or `&format=json`) |
| GET | `/api/export/left.csv` | Topology CSV (use `session_id` after compare) |
| GET | `/api/export/right.csv` | Topology CSV |
| GET | `/api/export/comparison.csv` | Diff report CSV |
| GET | `/health` | Liveness |

## Tests

```bash
pytest
```

## Project layout

```
app/           FastAPI, routes, services, adapters, templates
config/        YAML environment and identity mapping
tests/         Unit tests for compare + CSV
data/          SQLite FTS index (created at runtime, gitignored)
```

## Roadmap

- **Phase 3:** Real connectors, presets, disk cache, settings UI, audit
- **Phase 4:** Edge structure diff, export manifest JSON, optional Elasticsearch backend

See the product spec in project documentation (`autosys-process-scheduler-comparison-spec.md`).
