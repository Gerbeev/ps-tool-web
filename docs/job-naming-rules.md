# Scheduler Job Naming Rules

This document defines the structural naming convention used to derive cross-environment job identity. It is intentionally generic and must not contain concrete business codes, environment names, job names, or the literal shared prefix.

## Structure

A scheduler job name is composed, in order, of:

1. **Common prefix** — a fixed prefix shared by jobs covered by this convention. The literal value is environment-independent and is treated as a structural validation element, not as business identity.
2. **Business code** — a numeric application/business identifier exactly four digits long.
3. **Environment token** — the environment identifier embedded in the job name. Supported structural forms are two-character and four-character uppercase alphanumeric tokens. The token must ultimately be validated against configured environment aliases rather than accepted from length alone.
4. **Job-specific name** — the remaining non-empty part of the scheduler job name. This identifies the actual workload/job inside the business application.

The components are separated by underscores. The common prefix may itself contain underscores, so parsing must not assume a fixed number of prefix segments.

## Cross-Environment Identity

When the same workload is compared across environments, the environment token must not participate in the canonical identity.

The canonical cross-environment identity is therefore derived from:

```text
business_code + job_specific_name
```

The common prefix is excluded because it is globally structural. The environment token is excluded because it is the dimension intentionally being varied during cross-environment comparison.

The business code is retained. Jobs belonging to different business applications must not be paired merely because their job-specific suffixes are equal.

## Parsing Requirements

The machine-readable source of truth is `config/job_naming_rules.yaml`.

Parsing must:

- require a full structural match;
- require a four-digit business code;
- accept only the configured environment token forms;
- validate the extracted environment token against scheduler/environment configuration when the integration supplies the relevant aliases;
- preserve the complete job-specific remainder;
- return an unresolved identity when the name cannot be parsed safely rather than guessing component boundaries.

The naming rule is an identity aid only. It must not be used to infer execution dependencies, topology containment, scheduler status, or any other runtime semantics.

## Intended Matching Flow

For cross-environment comparison, identity resolution should eventually use this order:

1. explicit verified identity mapping, when one exists;
2. structured naming-rule parsing;
3. canonical key based on business code plus normalized job-specific name;
4. existing conservative fallback matching only when structured identity is unavailable.

Ambiguous or duplicate canonical identities must remain conflicts; the engine must never resolve them by selecting the first candidate.

## Cross-environment comparison behavior

The comparison engine uses this naming contract as a fallback identity strategy after explicit identity mappings. For a parsed scheduler job name, the canonical comparison identity contains the four-digit business code and the job-specific remainder, while the embedded environment token is excluded.

This means jobs from the same business group match when only their environment token differs. A different business code or a different job-specific remainder produces a different identity. The embedded environment token is validated by naming structure (two or four uppercase alphanumeric characters), not by requiring an exact match to the connection-catalog environment code, because scheduler job names may use environment aliases.

If a name does not satisfy the structured naming rule, the engine does not guess: it falls through to the existing explicit/legacy identity behavior.
