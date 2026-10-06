# Endpoint Adapter Contract

## Boundary

`ps-tool-web` integrates with two bank-internal service endpoints:

```text
AutoSys endpoint -----------------> AutoSysAdapter -----------+
                                                              |
                                                              v
                                                     TopologySnapshot
                                                              |
                                                              v
                                                     Comparison Engine
                                                              ^
                                                              |
Process Scheduler endpoint ------> ProcessSchedulerAdapter ---+
             |
             +-- internal Cosmos DB / persistence (opaque to this tool)
```

The comparison engine must never depend on the transport DTO shape, Process Scheduler's Cosmos DB schema, or its internal C# persistence implementation.

## Adapter Responsibilities

Each endpoint adapter is responsible for:

1. calling its configured `endpoint_url`;
2. applying bank-approved authentication;
3. using bounded timeouts and retries for idempotent reads;
4. validating the endpoint response sufficiently to avoid silently creating partial snapshots;
5. mapping endpoint DTOs into `SnapshotJob`, `DependencyEdge`, and `TopologySnapshot`;
6. declaring comparison-field coverage via `AdapterCapabilities`;
7. preserving useful non-comparable native metadata in `SnapshotJob.attributes`;
8. adding minimal `FieldEvidence` for non-obvious mappings.

## Engine Responsibilities

The engine owns identity matching, topology/dependency validation, AutoSys semantic normalization, definition/runtime comparison, partial coverage handling, mismatch reporting, search/export, and UI rendering.

## Endpoint Failure Semantics

Adapters must distinguish source failure from an empty scheduler result.

Examples that should raise/return an adapter failure rather than an empty snapshot:

- authentication/authorization failure;
- endpoint timeout after bounded retry policy;
- HTTP 5xx or gateway failure;
- incompatible response schema;
- truncated pagination where completion cannot be proven;
- response missing required identity/topology fields.

A legitimate response containing zero jobs is valid only when the endpoint contract confirms that zero jobs is a complete result for the requested scope.

## Pagination

If an endpoint paginates jobs/topologies, the adapter must exhaust all pages (or use a server-side export/bulk endpoint) before building a snapshot. Never compare page 1 from one scheduler against a complete snapshot from the other.

Record retrieval metadata in `TopologySnapshot.metadata`, for example:

```python
{
    "source": "process_scheduler_endpoint",
    "pages": 12,
    "complete": True,
    "api_version": "...",
}
```

Do not store credentials or sensitive payloads in metadata.

## Recommended Bank-Side Adapter Shape

```python
class BankProcessSchedulerAdapter(SchedulerAdapter):
    scheduler_type = SchedulerType.PROCESS_SCHEDULER

    def __init__(self, environment: EnvironmentEntry) -> None:
        self.environment = environment
        self.endpoint_url = environment.endpoint_url.rstrip("/")
        if not self.endpoint_url:
            raise ValueError("Process Scheduler endpoint_url is required")

    def capabilities(self) -> AdapterCapabilities:
        ...

    def health_check(self, environment_id: str) -> bool:
        ...

    def fetch_topology(self, context: ComparisonContext) -> TopologySnapshot:
        payload = self._fetch_complete_endpoint_payload(context)
        return self._map_payload(payload, context)

    def fetch_job_detail(
        self,
        context: ComparisonContext,
        job_uid: str,
    ) -> SnapshotJob | None:
        ...
```

The exact request paths, auth, DTOs and pagination are intentionally left bank-specific.

## Process Scheduler Storage

The Process Scheduler endpoint may itself read Cosmos DB. That is an implementation detail of Process Scheduler, not an integration responsibility of this application.

Benefits of keeping this boundary:

- no Cosmos credentials in `ps-tool-web`;
- no coupling to Cosmos containers/partition keys/schema migrations;
- endpoint remains responsible for interpreting its own C# domain model;
- the comparison engine remains portable and testable using synthetic endpoint fixtures.

## Process Scheduler full-job detail

The observed Process Scheduler detail response is now represented by `ProcessSchedulerJobReference` on `SnapshotJob.process_scheduler`. Real Process Scheduler adapters should populate this typed source object before building parity projections. The currently observed wire fields are `Box`, `ConditionExpression`, `Context`, `Description`, `JobType`, `LastFinishTime`, `LastStartTime`, `Name`, `Owner`, `Schedule`, `StartAtTime`, `StartAtTimeForce`, and `Status`. Unknown future DTO fields are preserved by the source model.

Do not treat the native source object itself as comparison truth. Project only verified semantic equivalents into normalized runtime fields / `autosys` parity fields. In particular, `Context` and `StartAtTimeForce` have no assumed AutoSys equivalent, and `Box` / `ConditionExpression` must not be used to invent containment or dependency edges until nested/non-null examples establish their exact endpoint semantics.
