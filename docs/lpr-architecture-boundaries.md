# LPR Architecture Boundaries

This repository now treats LPR as three explicit systems with one shared contract root.

## Cut Line

The old mixed editor/runtime/benchmark flow is frozen.

Allowed on the old path:
- critical bug fixes
- contract drift fixes required for current builds/tests
- compatibility fixes needed to finish the v2 cutover

Not allowed on the old path:
- new benchmark semantics added only in UI code
- new review/provenance logic derived in the host instead of the runtime
- new dataset rules enforced only by ad hoc scripts
- new JSON payloads hand-mirrored outside `schemas/`

## System Boundaries

### Desktop Host

Owns:
- request lifecycle
- cancellation
- window coordination
- analysis module state for per-file sessions and runtime status
- evidence export orchestration from typed analysis state

Does not own:
- benchmark aggregation
- review decision policy
- provenance derivation
- dataset semantics

### Python Runtime

Owns:
- frame/interval analysis use cases
- typed review decisions
- typed provenance
- analysis strategies and policies
- runtime contract validation

Does not own:
- benchmark reports
- benchmark run ledgers
- dataset registry semantics
- desktop window/session coordination

### Benchmark System

Owns:
- suite validation and inspection
- dataset/case/run semantics
- runtime broker protocol for benchmark execution
- run ledgers
- evaluation and reports
- gate policy

Does not own:
- runtime internals
- UI session state
- host cancellation logic

## Source Of Truth Policy

Shared contract rules:
- cross-boundary contracts live under `schemas/`
- generated TypeScript and Rust payloads must come from schema generation, not manual edits
- benchmark suite and run bundle validation must use repo-level shared schemas plus semantic validation
- runtime broker requests/responses must carry an explicit protocol version

## Dataset Policy

Allowed dataset roots:
- `datasets/` for local raw datasets and local evaluation media
- materialized benchmark copies under runtime/benchmark workspace runtime areas when a tool needs immutable prepared inputs

Required per-case provenance metadata:
- dataset
- split when known
- category or dominantCategory
- sourceMode when the materializer knows it

Prohibited:
- scattering raw datasets at the repository root
- app UI code reaching into arbitrary dataset folders as an implicit dependency
- benchmark cases without dataset provenance metadata

## Artifact Policy

Raw and derived artifacts are separated:
- raw local datasets stay under `datasets/`
- benchmark artifacts live under `.runtime/benchmark-tool/`
- runtime transient artifacts live under runtime-owned `.runtime/` areas
- exported user-facing evidence bundles remain explicit user outputs, not hidden benchmark state

## Job Lifecycle Policy

LPR job lifecycle is:
- idle
- queued
- running
- completed
- failed
- cancelled by explicit request handling in the host/runtime bridge

Rules:
- the host owns visible job state transitions
- the runtime owns analysis result semantics
- stale request results must be ignored by request id
- cancellation must terminate the active runtime process or request path, not only flip UI state

## Cross-Layer Dependency Rules

Forbidden dependencies:
- Desktop Host importing benchmark internals
- Benchmark System importing runtime application internals
- Runtime deriving benchmark-only summaries in its analysis contracts
- UI components inventing review/provenance semantics from diagnostics dicts

Allowed dependencies:
- Desktop Host <-> Runtime through generated/shared contracts
- Benchmark System <-> Runtime through the versioned broker protocol
- all systems reading the same schema root for shared contract validation
