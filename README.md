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
npm run check:vnext
```

### Local Data Layout

Local test media belongs under `datasets/` instead of the repository root:

```text
datasets/
    dev-videos/
```

### Runtime Data Layout

All generated runtime data now lives under the repo-root `.runtime/` tree:

```text
.runtime/
    runs/
        <run-id>/
            ai-evidence/
            analysis/
    cache/
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
