# Traffic LPR Runtime

This folder is the standalone Python runtime project for the Traffic desktop app's local license-plate-recognition pipeline.

## Layout

- `traffic_lpr_runtime/entrypoints/` - CLI entrypoint and module bootstrap.
- `traffic_lpr_runtime/application/` - use-case orchestration for status, scanning, frame analysis, and interval analysis.
- `traffic_lpr_runtime/domain/` - value objects, DTOs, errors, and protocol-style interfaces.
- `traffic_lpr_runtime/infrastructure/` - OpenCV, Ultralytics, Fast-ALPR, and OCR adapters.
- `.venv/` - optional local virtual environment for the runtime project.
- `.runtime/` - optional runtime cache area for model assets and transient files.

## Local Setup

Use a Python 3.11 or 3.12 interpreter for this runtime environment.

```powershell
cd traffic-lpr-runtime
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

The desktop app looks for this runtime under `traffic-lpr-runtime/` and launches it with:

```powershell
python -m traffic_lpr_runtime <subcommand>
```

Quick manual check:

```powershell
'{}' | .\.venv\Scripts\python.exe -m traffic_lpr_runtime status
```

You can override discovery with:

- `TRAFFIC_LPR_PYTHON` - explicit Python executable.
- `TRAFFIC_LPR_RUNTIME_DIR` - explicit runtime project root.