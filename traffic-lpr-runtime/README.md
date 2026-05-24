# Traffic LPR Runtime

This folder is the standalone Python runtime project for the Traffic desktop app's local license-plate-recognition pipeline.

## Layout

- `traffic_lpr_runtime/entrypoints/` - CLI entrypoint and module bootstrap.
- `traffic_lpr_runtime/application/` - use-case orchestration for status, scanning, frame analysis, and interval analysis.
- `traffic_lpr_runtime/domain/` - value objects, DTOs, errors, and protocol-style interfaces.
- `traffic_lpr_runtime/infrastructure/` - OpenCV, Ultralytics, and Fast-ALPR adapters.
- `models/` - auto-downloaded detector weights used by the runtime.
- `.venv/` - optional local virtual environment for the runtime project.
- `../.runtime/` - repo-level runtime data root shared with the desktop host and benchmark tool.

The runtime now separates package assets from generated data:

- `traffic-lpr-runtime/models/` stores reusable model weights.
- `../.runtime/runs/<run-id>/` stores one execution's AI evidence, analysis artifacts, and benchmark outputs.
- `../.runtime/cache/vendor/` stores reusable vendor shims such as the downloaded `mambair` architecture.
- `../.runtime/cache/benchmark/` stores benchmark suites, imports, materialized datasets, and generated local manifests.

## Local Setup

Use a Python 3.11 or 3.12 interpreter for this runtime environment.

```powershell
cd traffic-lpr-runtime
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall --index-url https://download.pytorch.org/whl/cu128 torch torchvision
```

If this environment was created before the multi-source benchmark update, run `.\.venv\Scripts\python.exe -m pip install -e .` again so `remotezip` is available for the UC3M-LP remote archive workflow.

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

## Benchmark Workflow

The runtime now includes a `benchmark-run` subcommand so you can turn difficult moving-camera clips into a repeatable hard-case benchmark.

Example usage:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < benchmarks\manifests\templates\sample-manifest.json
```

Each case can target either `frame` or `interval` mode and may include `analysisOptions` for ablations such as:

- `trackerMode`: `legacy`, `botsort`, or `bytetrack`
- `fusionMode`: `legacy` or `aligned-char`
- `restorationMode`: `off`, `gated`, `mambairv2`, `mambairv2-x2`, or `mambairv2-x4`
- `persistArtifacts`: store cropped / rectified / restored intermediate images under `../.runtime/runs/<run-id>/analysis/`
- `ocrModelNames`: compare multiple OCR heads on the same plate crop

Start by copying [benchmarks/manifests/templates/sample-manifest.json](benchmarks/manifests/templates/sample-manifest.json) and replacing the placeholder `sourcePath`, `selectedTargetBox`, and `expectedText` values with your own difficult cases.

The benchmark output includes per-case exact match, top-3 match, and character error rate so you can compare tracker / fusion / restoration changes against the same hard-case set.

The benchmark output now also includes localization recall / IoU when ground-truth boxes are present, accepted-candidate margin, confidence-calibration bins, failure-taxonomy summaries, interval track-consistency metrics, and p50 / p95 latency.

If you want a public benchmark set that does not depend on your own clips, see [benchmarks/README.md](benchmarks/README.md) and run either:

- `benchmarks/scripts/prepare_public_benchmark.py` for the existing CCPD-only hard-case manifest
- `benchmarks/scripts/prepare_multisource_benchmark.py --datasets ccpd uc3m-lp` for a more diverse public benchmark that adds UC3M-LP as a European counterweight

The UC3M-LP path uses HTTP range reads against the published Zenodo archive, so the generator can sample real cases without forcing a full archive download before manifest creation.

If you already have local AOLP and UFPR-ALPR datasets under `../datasets/aolp/` and `../datasets/ufpr-alpr/`, you can fold them into the same generator:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\scripts\prepare_multisource_benchmark.py --datasets aolp ufpr-alpr --per-category 12 --ufpr-split testing
```

That command writes machine-local manifests under `../.runtime/cache/benchmark/manifests/local/multisource/` and materializes any needed UFPR interval videos under `../.runtime/cache/benchmark/datasets/local-multisource/`.

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

When this happens, diagnostics still include a `selection` block for developer inspection, but the runtime now emits formal `review` and `provenance` payloads directly in the analysis response. The desktop host and benchmark pipeline consume those contract fields instead of re-deriving review state from diagnostics.