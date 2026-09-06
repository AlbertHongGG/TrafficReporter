# Traffic LPR Runtime

This folder is the standalone Python runtime project for the Traffic desktop app's local license-plate-recognition pipeline.

## Layout

- `traffic_lpr_runtime/entrypoints/` - CLI entrypoint and module bootstrap.
- `traffic_lpr_runtime/application/` - use-case orchestration for status, scanning, frame analysis, and interval analysis.
- `traffic_lpr_runtime/domain/` - value objects, DTOs, errors, and protocol-style interfaces.
- `traffic_lpr_runtime/infrastructure/` - OpenCV, Ultralytics, and Fast-ALPR adapters.
- `models/` - auto-downloaded detector weights used by the runtime.
- `.venv/` - optional local virtual environment for the runtime project.
- `../.runtime/` - repo-level runtime data root shared with the desktop host.

The runtime now separates package assets from generated data:

- `traffic-lpr-runtime/models/` stores reusable model weights.
- `../.runtime/runs/<run-id>/` stores one execution's AI evidence and analysis artifacts.
- `../.runtime/cache/vendor/` stores reusable vendor shims such as the downloaded `mambair` architecture.

## Local Setup

Use a Python 3.11 or 3.12 interpreter for this runtime environment.

```powershell
cd traffic-lpr-runtime
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall --index-url https://download.pytorch.org/whl/cu128 torch torchvision
```

The final command is required on NVIDIA Windows machines. `pip install -e .` pulls the CPU-only PyTorch wheel from PyPI by default, while the local LPR pipeline needs the CUDA-enabled `torch` and `torchvision` builds so that:

- the Ultralytics vehicle detector runs on `cuda:0`
- the ONNX Runtime plate detector/OCR stack can preload CUDA and cuDNN DLLs

Vehicle detector weights are stored under `traffic-lpr-runtime/models/`. If the preferred weight file is missing, the runtime will download it into that directory automatically on first use.

TensorRT is optional. The runtime is configured to use `CUDAExecutionProvider` directly and does not require a local TensorRT installation.

The desktop app looks for this runtime under `traffic-lpr-runtime/` and launches it with:

```powershell
python -m traffic_lpr_runtime <subcommand>
```

Quick manual check:

```powershell
'{}' | .\.venv\Scripts\python.exe -m traffic_lpr_runtime status
.\.venv\Scripts\python.exe - <<'PY'
import torch
print(torch.cuda.is_available(), torch.version.cuda)
PY
```

You can override discovery with:

- `TRAFFIC_LPR_PYTHON` - explicit Python executable.
- `TRAFFIC_LPR_RUNTIME_DIR` - explicit runtime project root.

## AI Evidence Workflow

The AI Evidence pipeline has three LLM-guided stages before the deterministic interval analysis pass:

- `coarse`: sample a sparse storyboard across the full source clip so the model can localize the rough event interval.
- `fine`: sample a denser storyboard inside the padded coarse interval so the model can tighten the start/end points, choose the primary anchor frame, and pick the narrative keyframes.
- `target`: inspect the anchor frame plus candidate crops so the model can decide which detected vehicle actually matches the user's description.

When the desktop user presses `Run` in the AI Evidence window, the full flow is:

1. The desktop host creates a run id in the shared `yymmdd-hhmmss-randomhex` format.
2. The Rust host sends the AI request to `python -m traffic_lpr_runtime` and reserves `../.runtime/runs/<run-id>/ai-evidence/` for the run.
3. Python renders the `coarse/` storyboard, asks the AI model to localize the rough interval, then renders the `fine/` storyboard.
4. Python asks the AI model to select the refined interval, anchor frame, and keyframes.
5. Python renders target-reference crops under `target-resolution/` and asks the AI model to resolve the intended vehicle.
6. Python runs the deterministic `analyze-interval` workflow over the refined interval to get target tracks, OCR candidates, review/provenance payloads, and accepted candidate state.
7. Python renders final keyframes under `keyframes/` and returns the structured response.
8. Rust exports the resolved clip into the same run folder as `../.runtime/runs/<run-id>/ai-evidence/clip.mp4`.
9. AI call logs for `coarse`, `fine`, and `target` are written under `../.runtime/runs/<run-id>/ai-logs/`.

## Evidence Export

The desktop export action now writes an evidence bundle instead of only a single PNG + JSON pair. The bundle contains:

- `source-frame.png` for the exported editor frame
- `decision-frames/` with copied original / rectified / enhanced / restored / working crops when those artifacts exist
- per-frame `frame.json` metadata for the selected decision frames
- the top-level snapshot JSON you chose from the export dialog

This makes it possible to review not only the final string, but also which frame(s) supported that decision and what the preprocessing stack produced for each one.

## Reliability Gates

Frame and interval analysis now apply reliability gates before auto-accepting a candidate. The runtime can keep a candidate as a suggested result while leaving `acceptedCandidateId` empty when any of these checks fail:

- low accepted confidence
- low margin versus the next candidate
- insufficient multi-frame support for interval results
- Taiwan-format mismatch when `countryHints` prefer Taiwan

When this happens, diagnostics still include a `selection` block for developer inspection, but the runtime now emits formal `review` and `provenance` payloads directly in the analysis response. The desktop host consumes those contract fields instead of re-deriving review state from diagnostics.