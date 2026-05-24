# Media Editor

A Tauri-based desktop application for media editing and YouTube downloading. Built with React, TypeScript, and Rust.

## Getting Started

### Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [Rust](https://www.rust-lang.org/tools/install) (stable)
- [Tauri CLI prerequisites](https://v2.tauri.app/start/prerequisites/)

### External Binaries

The following binaries must be placed in `src-tauri/bin/` for full functionality:

| Binary | Purpose | Source |
|--------|---------|--------|
| `yt-dlp.exe` | YouTube media downloading | [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases) |
| `ffmpeg.exe` | Media encoding & export | `winget install Gyan.FFmpeg` |
| `ffprobe.exe` | Media file inspection | Included with ffmpeg |

> **Note:** These binaries are **not** tracked by Git (`.gitignore`). After cloning, you must manually place them in `src-tauri/bin/`.

### Additional System Dependencies

- **Deno**: Required by yt-dlp for solving YouTube signature challenges. Install via `winget install DenoLand.Deno`.

### Install & Run

```bash
npm install
npm run tauri dev
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
| `npm run build:exe` | Build standalone exe only (fast, no installer) | `src-tauri/target/release/media-editor.exe` |
| `npm run build:installer` | Build NSIS installer (includes bundled binaries) | `src-tauri/target/release/bundle/nsis/media-editor_*_x64-setup.exe` |
| `npm run build:portable` | Build exe + copy binaries into portable folder | `dist-portable/` |

### Standalone EXE (Portable)

The portable distribution requires the exe and `bin/` folder together:

```
dist-portable/
├── media-editor.exe
└── bin/
    ├── ffmpeg.exe
    ├── ffprobe.exe
    └── yt-dlp.exe
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

The installer will be at `src-tauri/target/release/bundle/nsis/media-editor_0.1.0_x64-setup.exe`.

---

## Troubleshooting (YouTube Downloader)

### 1. yt-dlp version: Use Nightly
The **stable** version of yt-dlp cannot access most YouTube formats due to PO Token requirements. The **nightly** build includes improved client strategies that bypass these restrictions.
- **Update to nightly**: `yt-dlp.exe --update-to nightly`

### 2. Signature solving failed
Ensure **Deno** is installed and accessible in your terminal (`deno --version`). yt-dlp uses Deno to solve YouTube's JavaScript signature challenges.

### 3. `[Errno 22] Invalid argument` during download
Caused by **IPv6** connectivity issues with YouTube CDN on Windows. The app uses `--force-ipv4` to force all connections through IPv4.

### 4. Failed to decrypt with DPAPI (Windows)
Avoid `--cookies-from-browser` on Windows — Chrome/Edge lock the cookie database while running, and DPAPI decryption fails. The current implementation avoids cookies entirely.

### 5. HTTP Error 429: Too Many Requests
Usually resolved by having Deno installed (for JS challenge solving) and using the nightly build.
