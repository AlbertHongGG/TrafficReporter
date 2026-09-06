# Traffic vNext Architecture

This document is the active architecture charter for the in-repo vNext rebuild.

## Product Cut Line

The primary product is now the traffic editor stack:

- desktop editor UI
- Rust host/runtime broker
- Python analysis runtime
- shared contracts and protocol

Legacy downloader entrypoints have been removed from the active desktop host. Any remaining historical references should be treated as cleanup debt, not product surface.

## Current vNext Surfaces

- `src/vnext/`
  - frontend session store and revision-aware window projections
- `schemas/protocol/`
  - runtime envelope schemas and future protocol negotiation surface
- `schemas/lpr/`
  - shared LPR job lifecycle, degraded tracking, and range-coverage contract surface
- `src-tauri/src/editor/runtime_broker.rs`
  - explicit worker lifecycle, timeout, cancellation, and retry boundary
- `src-tauri/src/editor/mod.rs`
  - Tauri command boundary and lifecycle/result mapping for streamed LPR jobs
- `traffic-lpr-runtime/traffic_lpr_runtime/protocol/`
  - versioned runtime envelopes, request context, and streamed progress payload builders
- `traffic-lpr-runtime/traffic_lpr_runtime/vnext/`
  - runtime service container and use-case registry

## Rules

- Main window owns editor session state.
- Child windows consume revisioned snapshots and must drop stale revisions.
- Rust host owns request lifecycle, worker supervision, timeout, and cancellation.
- Observable LPR job progress must originate in the Python `serve` worker and stream through the Rust broker to the UI; host-side synthetic start/completion events should stay minimal.
- Python runtime owns analysis semantics.
- Interactive frame analysis must prefer a fast path over heavy restoration/comparison work.
- Interval analysis must return coverage-aware degraded results before it escalates to hard failure.
- Cross-boundary contracts must originate from `schemas/`.

## Verification Gates

- `npm run check:lpr-contracts`
- `npm run test:vnext:frontend`
- `npm run test:vnext:runtime`
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `cargo test --manifest-path src-tauri/Cargo.toml runtime_broker`
- `npm run build`

## Transitional Notes

- The vNext session store currently wraps the existing editor reducer instead of replacing editor domain logic outright.
- The Rust runtime broker preserves the current worker protocol version while enforcing a host-side timeout boundary and forwarding streamed `kind: "progress"` envelopes until the final result arrives.
- The Python runtime registry currently adapts existing workflows as use cases; it is the intermediate step before deeper workflow extraction.
- Interactive frame analysis now forces an initial fast-path option profile in the runtime so the first usable result can return without the heaviest comparison/restoration path.
- Interval analysis now distinguishes `completed` vs `degraded` results with tracking coverage metadata instead of treating every anchor drift as an unconditional hard failure.