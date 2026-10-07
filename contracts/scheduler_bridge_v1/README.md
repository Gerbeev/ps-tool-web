# scheduler-bridge/v1 contract artifacts

These JSON Schemas are the machine-readable snapshot of the frozen workstation boundary.

- `request.schema.json` — request envelope and context.
- `response-envelope.schema.json` — response envelope, structured errors and capabilities.
- `topology-data.schema.json` — `fetch_topology.data`.
- `job.schema.json` — reusable job object for topology/detail responses.

Protocol semantics and operation-specific response shapes are defined in `docs/workstation-connector-protocol-v1.md`.

**Compatibility rule:** do not make breaking changes to v1. Additive fields must remain optional. Any incompatible change requires a new `scheduler_bridge_v2` contract and explicit dual-version support in the portable bridge client during migration.
