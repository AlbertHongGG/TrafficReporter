# Traffic vNext Architecture

This document is the active architecture charter for the in-repo vNext rebuild.

## Product Cut Line

The primary product is now the traffic editor stack:

- desktop editor UI
- Rust host/runtime broker
- Python analysis runtime
- shared contracts and protocol
- benchmark client

Legacy downloader entrypoints have been removed from the active desktop host. Any remaining historical references should be treated as cleanup debt, not product surface.

## Current vNext Surfaces

- `src/vnext/`
  - frontend session store and revision-aware window projections
- `schemas/protocol/`
  - runtime envelope schemas and future protocol negotiation surface
- `src-tauri/src/editor/runtime_broker.rs`
  - explicit worker lifecycle, timeout, cancellation, and retry boundary
- `traffic-lpr-runtime/traffic_lpr_runtime/vnext/`
  - runtime service container and use-case registry

## Rules

- Main window owns editor session state.
- Child windows consume revisioned snapshots and must drop stale revisions.
- Rust host owns request lifecycle, worker supervision, timeout, and cancellation.
- Python runtime owns analysis semantics.
- Benchmark tooling must share runtime protocol semantics with the product runtime.
- Cross-boundary contracts must originate from `schemas/`.

## Verification Gates

- `npm run check:lpr-contracts`
- `npm run test:vnext:frontend`
- `npm run test:vnext:runtime`
- `npm run test:vnext:benchmark`
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `npm run build`

## Transitional Notes

- The vNext session store currently wraps the existing editor reducer instead of replacing editor domain logic outright.
- The Rust runtime broker preserves the current worker protocol version while enforcing a host-side timeout boundary.
- The Python runtime registry currently adapts existing workflows as use cases; it is the intermediate step before deeper workflow extraction.