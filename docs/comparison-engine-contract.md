# Comparison Engine Contract

## Goal

The comparison engine determines whether an AutoSys workload and a Process Scheduler topology are behaviorally equivalent enough for migration validation while remaining independent of either system's connector implementation.

## Comparison Dimensions

### Identity

Jobs are paired by logical identity. Ambiguous identities are never auto-selected.

Identity resolution priority is:

1. explicit scheduler-to-scheduler mappings;
2. configured legacy regex mappings;
3. structured cross-environment job-name identity;
4. legacy exact/normalized-name fallback.

For structured scheduler names, the cross-environment identity is composed from the four-digit business code plus the job-specific remainder. The embedded environment token is excluded, so the same business job can match across environments. The business code is never removed: jobs from different business groups must not match even if their remaining name is identical. Likewise, a different job-specific remainder produces a different identity.

The embedded environment token is interpreted structurally and is not required to equal the connection-catalog environment code because scheduler names may use environment aliases.

### Topology Containment

`parent_uid` represents structural membership only. For matched jobs, the engine compares the logical identity of the parent as synthetic field `topology_parent`.

### Execution Dependencies

`DependencyEdge` contains only real execution prerequisites. The engine compares predecessor logical IDs, dependency kind, and normalized dependency condition.

Complex native condition semantics that cannot be represented reliably by edges must also be projected into the configured AutoSys `condition` field or marked unsupported/unknown.

### Static AutoSys-equivalent Definition

Configured JIL-equivalent fields are compared using semantic normalization rather than raw text where supported.

### Runtime

Normalized status, resolved command, exit code, actual start/end and timing deviation are compared only when the corresponding adapter declares runtime coverage.

## Three-State Comparison Behavior

A field comparison does not have only match/mismatch outcomes.

1. **match** — both sides support the field and normalized values are equivalent;
2. **mismatch** — both sides support the field and normalized values differ;
3. **not comparable** — either side declares unsupported, unknown, or not-applicable coverage.

This prevents missing adapter functionality from being misreported as a migration defect.

## Coverage

`ComparisonSummary` includes:

- total/matched/left-only/right-only jobs;
- status/timing/parameter mismatch counts;
- per-parameter mismatch counts;
- total not-comparable comparisons;
- per-parameter not-comparable counts;
- identity conflict count.

A comparison with zero mismatches but large not-comparable coverage must not be interpreted as full parity.

## Evidence

Adapters may attach field provenance using `comparison_evidence`. Evidence is copied into mismatch and not-comparable records and is intended for debugging source-to-normalized mapping.

## Validation vs Comparison

Snapshot validation answers: "Is this adapter output structurally trustworthy enough to compare?"

Comparison answers: "Given two trustworthy normalized snapshots, where do supported semantics differ?"

These concerns are intentionally separate.
