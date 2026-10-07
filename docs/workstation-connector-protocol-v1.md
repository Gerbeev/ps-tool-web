# Workstation Connector Protocol v1

## Decision

Real AutoSys and Process Scheduler integration is **out of process**. The portable web application never imports bank-local connector code.

```text
Portable web project
  FastAPI / Snapshots ingestion
          |
          v
  ExternalBridgeAdapter
          |
          | scheduler-bridge/v1
          | one JSON request on stdin
          | one JSON response on stdout
          v
workstation_connectors/
  autosys_connector.py ------------> existing bank AutoSys Python tool/API
  process_scheduler_connector.py ---> existing Process Scheduler Python tool/API
```

This is the compatibility boundary for the project. Protocol v1 is frozen: existing field meanings and operation semantics must not be changed. Future incompatible changes must be introduced as `scheduler-bridge/v2` while v1 remains supported until the workstation scripts are intentionally upgraded.

## Why this boundary

The web project changes frequently outside the bank. The connector scripts can only be created/edited on the workstation and cannot be exported back. Therefore the connector must not subclass `SchedulerAdapter`, import `app.models`, or depend on the repository's Python package layout.

The bridge DTO is deliberately separate from `TopologySnapshot`. Internal models may evolve; only the translator in `app/adapters/bridge_contract.py` changes.

## Fixed workstation filenames

When `USE_MOCK_ADAPTERS=false`, the application invokes exactly:

```text
workstation_connectors/autosys_connector.py
workstation_connectors/process_scheduler_connector.py
```

The directory is configurable only through `PS_TOOL_CONNECTOR_DIR`; the filenames are not configurable from the UI or environment YAML. The scripts are git-ignored.

For a workstation that receives complete project-folder replacements, prefer a persistent directory **outside the repository** (for example a bank-approved local workspace) and point `PS_TOOL_CONNECTOR_DIR` to it. This prevents a web-project refresh from deleting the bank-local implementation. The in-repo `workstation_connectors/` directory remains the convenient default.

Copy the three starter files from `examples/workstation_connectors/` manually, or run `setup-workstation-connectors.cmd <persistent-directory>`:

```text
bridge_v1_runtime.py
autosys_connector.py
process_scheduler_connector.py
```


## Transport rules

Each invocation is a short-lived local child process.

- Request: exactly one UTF-8 JSON object on `stdin`.
- Response: exactly one UTF-8 JSON object on `stdout`.
- Logs/diagnostics: `stderr` only.
- No HTTP listener, local port, socket, shared DB, or web-app import is required.
- The web process uses an argument array, never `shell=True`.
- Default timeout: 120 seconds (`PS_TOOL_CONNECTOR_TIMEOUT_SEC`).
- Default accepted response size: 128 MB (`PS_TOOL_CONNECTOR_MAX_RESPONSE_MB`).
- A connector source/API failure is returned as a structured `ok=false` response. A non-zero process exit code is reserved for launcher/runtime failure.

## Request envelope

```json
{
  "protocol": "scheduler-bridge",
  "version": 1,
  "request_id": "uuid",
  "operation": "fetch_topology",
  "context": {
    "environment_id": "autosys-u1",
    "environment": "U1",
    "scheduler": "autosys",
    "host": "configured-host-or-endpoint",
    "as_of_kind": "business_date",
    "as_of_value": "2026-10-07",
    "root_box": "optional-root",
    "topology_id": null
  },
  "job_uid": null
}
```

`host` is the operator-configured target from the scheduler environment YAML. Credentials, tokens, passwords and certificates must not be passed through this field or stored in YAML; obtain them inside the workstation connector from the bank-approved mechanism.

## Operations

| Operation | Request addition | Success `data` |
|---|---|---|
| `health` | none | `{"healthy": true, "message": ""}` |
| `list_roots` | none | `{"roots": ["root-a", "root-b"]}` |
| `fetch_topology` | none | topology payload below |
| `fetch_job_detail` | `job_uid` required | `{"job": <job-or-null>}` |

## Success response envelope

```json
{
  "protocol": "scheduler-bridge",
  "version": 1,
  "request_id": "same uuid as request",
  "ok": true,
  "data": {},
  "error": null,
  "capabilities": {
    "topology": true,
    "dependencies": true,
    "runtime": true,
    "job_detail": true,
    "root_listing": true,
    "autosys_projection": true,
    "strict_parameter_support": true,
    "parameter_support": {
      "command": "supported",
      "watch_file_min_size": "not_applicable"
    }
  }
}
```

The app validates protocol/version and requires the response `request_id` to match the request.

## Error response envelope

```json
{
  "protocol": "scheduler-bridge",
  "version": 1,
  "request_id": "same uuid as request",
  "ok": false,
  "data": {},
  "error": {
    "code": "source_timeout",
    "message": "AutoSys query timed out",
    "retryable": true,
    "details": {}
  }
}
```

Do not return an empty topology for authentication failure, timeout, incompatible source schema, partial pagination, or any other incomplete retrieval. Return a structured failure instead.

## `fetch_topology` data

```json
{
  "fetched_at": "2026-10-07T12:00:00Z",
  "jobs": [],
  "dependencies": [],
  "metadata": {
    "source": "bank-autosys-tool"
  }
}
```

A job uses this stable v1 shape:

```json
{
  "job_uid": "stable-native-or-derived-id",
  "scheduler_job_name": "JOB_NAME",
  "scheduler_native_id": "optional-native-id",
  "parent_uid": "optional-container-job-uid",
  "path_labels": ["Root", "Box"],
  "status": "success",
  "status_raw": "SU",
  "scheduled_start": null,
  "actual_start": "2026-10-07T10:00:00Z",
  "actual_end": "2026-10-07T10:03:12Z",
  "duration_sec": 192.0,
  "exit_code": 0,
  "autosys_jil": {
    "job_type": "CMD",
    "machine": "host-a",
    "command": "run-job",
    "condition": "s(PREVIOUS_JOB)"
  },
  "autosys_run": {
    "resolved_command": "run-job --date 2026-10-07",
    "exit_code": 0,
    "actual_start": "2026-10-07T10:00:00Z",
    "actual_end": "2026-10-07T10:03:12Z"
  },
  "process_scheduler": null,
  "attributes": {},
  "comparison_support": {},
  "comparison_evidence": {
    "command": {
      "source": "autosys_tool",
      "locator": "job.command",
      "note": ""
    }
  }
}
```

Allowed normalized status values are `pending`, `running`, `success`, `failure`, `killed`, `unknown`, `not_run`, and `disabled`. Preserve the source status in `status_raw`.

For Process Scheduler, populate `process_scheduler` with observed native fields and populate `autosys_jil` / `autosys_run` only for semantic equivalents that are actually verified. Never fabricate parity values just to make a comparison pass.

## Dependencies vs containment

`parent_uid` is topology/container membership only.

Execution dependencies are returned separately:

```json
{
  "from_uid": "job-a",
  "to_uid": "job-b",
  "kind": "finish_to_start",
  "condition": "optional source condition"
}
```

Allowed kinds: `finish_to_start`, `start_to_start`, `file_trigger`, `custom`.

Never infer `A -> B` merely because A and B are adjacent children of the same box/topology.

## Capability contract

For the first workstation implementation, `strict_parameter_support=false` is acceptable while mappings are being proven. Before relying on migration parity results, switch to `true` and declare support for every field in `config/autosys_compare_parameters.yaml` plus:

- `status`
- `dependencies`
- `topology_parent`

Values are `supported`, `unsupported`, `unknown`, or `not_applicable`.

## Workstation implementation rule

Only `autosys_connector.py` and `process_scheduler_connector.py` should contain bank-local imports and source calls. Keep `bridge_v1_runtime.py` unchanged. The connector implementation should convert source DTOs into the v1 dictionaries and return them; it should not contain web/UI/comparison logic.

## Verification

After copying/wiring connectors on the workstation:

```cmd
set USE_MOCK_ADAPTERS=false
python -m app.adapters.check --environment autosys-u1 --scheduler autosys --as-of 2026-10-07
python -m app.adapters.check --environment ps-u5 --scheduler process_scheduler --as-of 2026-10-07
```

Both checks must pass before the Snapshots workflow is used against real scheduler sources. Browse and Compare then consume only the generated snapshot catalog.

## Security and data handling

- Never store credentials in the project, YAML, request/response payload, or connector logs.
- Do not log full source DTOs or raw job command output.
- Runtime snapshots under `data/runtime/` remain git-ignored because job definitions, paths, owners and commands may be bank-sensitive.
- Keep connector scripts local to the workstation and out of Git; the repository ignores the fixed implementation filenames.
