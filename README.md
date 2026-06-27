# TrafficReporter

A Tauri-based desktop application for traffic video review, LPR analysis, and AI evidence workflows. Built with React, TypeScript, Rust, and a Python analysis runtime.

The repository is now in a vNext transition state:

- `src/vnext/` holds the new frontend session/windowing boundary.
- `schemas/protocol/` holds the new runtime envelope schema spine.
- `src-tauri/src/editor/runtime_broker.rs` is the new host-side runtime broker boundary.
- `traffic-lpr-runtime/traffic_lpr_runtime/vnext/` holds the new Python runtime registry/container layer.
- legacy downloader entrypoints have been removed from the active desktop host; the current product surface is analysis-first.

See `docs/traffic-vnext-architecture.md` for the current vNext cut line and verification rules.

## Getting Started

### Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [Rust](https://www.rust-lang.org/tools/install) (stable)
- [Tauri CLI prerequisites](https://v2.tauri.app/start/prerequisites/)

### External Binaries

The following binaries must be placed in `src-tauri/bin/` for full functionality:

| Binary | Purpose | Source |
|--------|---------|--------|
| `ffmpeg.exe` | Media encoding & export | `winget install Gyan.FFmpeg` |
| `ffprobe.exe` | Media file inspection | Included with ffmpeg |

> **Note:** These binaries are **not** tracked by Git (`.gitignore`). After cloning, you must manually place them in `src-tauri/bin/`.

### Install & Run

```bash
npm install
npm run tauri dev
```

### vNext Verification

The new architecture guardrails can be checked independently from the full legacy test suite:

```bash
npm run test:vnext:frontend
npm run test:vnext:runtime
npm run test:vnext:benchmark
npm run check:vnext
```

### Independent Benchmark Tool

The benchmark workflow now has its own repo-level entrance and does not live inside the desktop app UI:

```bash
npm run benchmark -- init-workspace
npm run benchmark -- validate --suite .runtime/cache/benchmark/suites/sample-template.json
npm run benchmark -- doctor --suite .runtime/cache/benchmark/suites/sample-template.json
npm run benchmark -- run --suite .runtime/cache/benchmark/suites/smoke-one.json --run-id smoke-gate --min-exact-rate 1.0 --min-top3-rate 1.0 --max-mean-cer 0.0 --min-plate-iou 1.0 --max-p95-latency-ms 60000
npm run benchmark -- profile-sweep --suite .runtime/cache/benchmark/suites/smoke-one.json --profiles balanced precision recovery
npm run benchmark -- validate-profile-catalog --file src/shared/config/lpr-analysis-profiles.json
npm run benchmark:test
```

Longer benchmark runs now emit resumable `progress.json` / `checkpoint.json` artifacts under `.runtime/runs/<run-id>/benchmark/` and can enforce benchmark gates directly from the CLI. Runtime-backed reports also include `analysis.json` / `analysis.md` so AOLP and UFPR results can be read by dataset, split, category, and broad failure source instead of only by merged averages.

Shared benchmark and LPR profile schemas now live under `schemas/` so the benchmark tool and runtime-facing JSON assets can evolve from one repo-level source of truth.

The architecture cut line, dataset policy, artifact policy, and cross-layer dependency rules are documented in `docs/lpr-architecture-boundaries.md`.

The LPR request/response contract is now generated from `schemas/lpr/lpr-contracts.json`. Regenerate the checked-in TypeScript and Rust payload definitions with:

```bash
npm run generate:lpr-contracts
npm run check:lpr-contracts
```

`npm run dev`, `npm run build`, and `npm test` now refresh those generated contracts automatically before running. `npm run check:lpr-contracts` is the non-mutating drift check for CI or pre-merge verification.

### Local Data Layout

Local datasets and local evaluation media now belong under `datasets/` instead of the repository root:

```text
datasets/
    aolp/
    ufpr-alpr/
    dev-videos/
```

`schemas/` stays at the repo root because it is shared by the frontend, Rust host, Python runtime, and benchmark tool. The old root-level `scripts/` folder is not needed for a single LPR contract generator, so that generator lives next to its owning LPR schema files instead.

### Runtime Data Layout

All generated runtime data now lives under the repo-root `.runtime/` tree:

```text
.runtime/
    runs/
        <run-id>/
            ai-evidence/
            analysis/
            benchmark/
    cache/
        benchmark/
            suites/
            imports/
            datasets/
            manifests/
        vendor/
```

`<run-id>` uses local time plus random suffix: `yymmdd-hhmmss-randomhex`. The desktop editor reuses that run id for LPR requests and AI evidence runs so logs, clips, keyframes, and analysis artifacts from one execution stay grouped together.

The editor toolbar now includes a `Compact` toggle. It controls current-frame export size and seeds the default compression mode shown in the export window for timeline media.

---

## Build & Distribution

### Build Commands

| Command | Description | Output |
|---------|-------------|--------|
| `npm run build:exe` | Build standalone exe only (fast, no installer) | `src-tauri/target/release/traffic-reporter.exe` |
| `npm run build:installer` | Build NSIS installer (includes bundled binaries) | `src-tauri/target/release/bundle/nsis/traffic-reporter_*_x64-setup.exe` |
| `npm run build:portable` | Build exe + copy binaries into portable folder | `dist-portable/` |

### Standalone EXE (Portable)

The portable distribution requires the exe and `bin/` folder together:

```
dist-portable/
├── traffic-reporter.exe
└── bin/
    ├── ffmpeg.exe
    └── ffprobe.exe
```

To create this package:

```bash
npm run build:portable
```

Then zip the `dist-portable/` folder and share it. The recipient must have **WebView2** installed (pre-installed on Windows 10 21H2+ and Windows 11).

### NSIS Installer

For a full installer that bundles everything including WebView2:

```bash
npm run build:installer
```

The installer will be at `src-tauri/target/release/bundle/nsis/traffic-reporter_0.1.0_x64-setup.exe`.
