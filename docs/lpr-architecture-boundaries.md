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
- run-scoped outputs live under `.runtime/runs/<run-id>/`
- benchmark cache state lives under `.runtime/cache/benchmark/`
- reusable runtime vendor/cache state lives under `.runtime/cache/vendor/`
- exported user-facing evidence bundles remain explicit user outputs, not hidden benchmark state

Run-id policy:
- user-facing LPR and AI requests should reuse a stable run id for the whole execution
- benchmark profile sweeps may create nested per-profile folders, but they still belong under one top-level run id
- run ids use local time plus random suffix: `yymmdd-hhmmss-randomhex`

AI evidence stage policy:
- `coarse` means sparse full-clip localization, not OCR
- `fine` means denser interval refinement plus keyframe selection
- `target` means anchor-frame vehicle resolution, not interval tracking
- final tracking/OCR semantics still come from the deterministic `analyze-interval` runtime workflow

Export compression policy:
- `compressionMode` is an explicit cross-layer contract field, not an optional host-side hint
- timeline export, AI evidence clip export, frame export, AI evidence keyframes, and evidence bundle user-facing images must use the same compression mode semantics
- compression mode must not silently change output dimensions; timeline exports may scale only when the user explicitly selects a lower resolution, and they must never upscale beyond the source dimensions
- audio bitrate remains a user-owned setting and must pass through unchanged on every user-facing video export surface that carries audio
- `standard` keeps higher-fidelity timeline settings and full-color PNG still-image outputs
- `compact` means lossy size reduction at the same dimensions: stronger H.264 inter-frame compression for timelines and lossy PNG quantization for user-facing still images
- AI runtime storyboard assets and ai-log JSON remain diagnostic artifacts by default; host-side finalization is responsible for compact-aware clip and user-facing keyframe outputs
- evidence bundles must not hardcode a still-image format that bypasses the selected compression mode, and user-facing still-image outputs must remain `.png`

Target evidence policy:
- AI evidence prompts live in a runtime-owned prompt catalog, not as hidden inline strings inside workflow code
- the target resolver prompt must be built from structured evidence payloads, not ad hoc OCR summary strings
- target candidate evidence must carry detection ids plus OCR candidate summaries so logs and prompts describe the same objects
- an exact OCR match to the description's plate hint is a strong prior, not an absolute override
- overriding that strong prior requires an explicit `contradicted` assessment from the target resolver output, not a silent branch
- if the provider fails and a strong prior exact match exists, the runtime may still fall back to that exact match deterministically
- user-facing AI images must not burn stage/frame/time headers into pixels; runtime logs keep the metadata, while final keyframes and target-resolution artifacts stay visually clean except for meaningful box annotations

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
