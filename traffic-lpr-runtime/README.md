# Traffic LPR Runtime

This folder is the standalone Python runtime project for the Traffic desktop app's local license-plate-recognition pipeline.

## Layout

- `traffic_lpr_runtime/entrypoints/` - CLI entrypoint and module bootstrap.
- `traffic_lpr_runtime/application/` - use-case orchestration for status, scanning, frame analysis, and interval analysis.
- `traffic_lpr_runtime/domain/` - value objects, DTOs, errors, and protocol-style interfaces.
- `traffic_lpr_runtime/infrastructure/` - OpenCV, Ultralytics, and Fast-ALPR adapters.
- `models/` - auto-downloaded detector weights used by the runtime.
- `.venv/` - optional local virtual environment for the runtime project.
- `.runtime/` - optional transient runtime cache area.

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

## Benchmark Workflow

The runtime now includes a `benchmark-run` subcommand so you can turn difficult moving-camera clips into a repeatable hard-case benchmark.

Example usage:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < benchmarks\sample-manifest.json
```

Each case can target either `frame` or `interval` mode and may include `analysisOptions` for ablations such as:

- `trackerMode`: `legacy`, `botsort`, or `bytetrack`
- `fusionMode`: `legacy` or `aligned-char`
- `restorationMode`: `off`, `gated`, `mambairv2`, `mambairv2-x2`, or `mambairv2-x4`
- `persistArtifacts`: store cropped / rectified / restored intermediate images under `.runtime/analysis/`
- `ocrModelNames`: compare multiple OCR heads on the same plate crop

Start by copying [benchmarks/sample-manifest.json](benchmarks/sample-manifest.json) and replacing the placeholder `sourcePath`, `selectedTargetBox`, and `expectedText` values with your own difficult cases.

The benchmark output includes per-case exact match, top-3 match, and character error rate so you can compare tracker / fusion / restoration changes against the same hard-case set.

If you want a public benchmark set that does not depend on your own clips, see [benchmarks/README.md](benchmarks/README.md) and run `benchmarks/prepare_public_benchmark.py` to build a balanced CCPD hard-case manifest from a directly downloadable public subset.