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
