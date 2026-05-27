# Benchmark Notes

Build benchmarks around target-centric hard cases from moving-camera footage.

## Layout

- `benchmarks/config/` stores curated official-suite selection policies.
- `benchmarks/scripts/` stores generator entrypoints and shared preparation helpers.
- `benchmarks/manifests/templates/` stores hand-authored templates such as the local dashcam sample manifest.
- `benchmarks/manifests/public/` stores checked-in legacy public manifests for exploratory or compatibility workflows.
- `../.runtime/cache/benchmark/cache/` stores disposable download caches.
- `../.runtime/cache/benchmark/datasets/` stores materialized benchmark images and interval clips.
- `../.runtime/cache/benchmark/manifests/local/official/` stores generated official local manifests.
- `../.runtime/cache/benchmark/manifests/public/official/` stores generated official public manifests.
- `../.runtime/cache/benchmark/suites/official/` stores imported benchmark-tool suites for the official gates.

Keep only reusable benchmark definitions under `benchmarks/`. Generated manifests, extracted images, remote downloads, smoke outputs, and one-off analysis artifacts belong under `.runtime/` and can be deleted safely.

Recommended annotation fields per case:

- `id`: stable case identifier
- `mode`: `frame` or `interval`
- `sourcePath`: absolute path to the original media
- `interval`: the narrowest useful time window around the target vehicle
- `anchorTimeMs`: frame where the target vehicle is easiest to select
- `selectedTargetBox`: normalized vehicle box on the anchor frame
- `expectedText`: normalized plate text without punctuation
- `countryHints`: country priors such as `['TW']`, `['ES', 'EU']`, or `['BR']`
- `tags`: conditions such as `blur`, `angle`, `small-plate`, `weather`, `low-light`, `high-exposure`, and `moving-camera`
- `analysisOptions`: ablation switches for tracker, fusion, restoration, and OCR comparison

Suggested benchmark splits:

- `development`: cases you iterate on every day
- `holdout`: cases you do not inspect while tuning
- `challenge`: worst failure cases that are allowed to be slow but should improve over time

The runtime returns per-case exact match, top-3 match, and character error rate. Use those together; exact match alone hides whether you are close or far from the right answer.

The benchmark runner also reports:

- plate / target localization recall and mean IoU when a manifest includes ground-truth boxes
- confidence calibration bins plus expected calibration error
- accepted-candidate margin and p50 / p95 latency
- interval-track stability signals such as prediction switch count, majority-vote exact match, and time-to-first-correct
- failure taxonomy buckets such as `target-missed`, `plate-localization-missed`, `ocr-disagreement`, and `fusion-unstable`

## Official Suite Workflow

Generate the official local gates with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\scripts\prepare_official_local_benchmarks.py
```

That workflow materializes the current official AOLP, LP2025, UFPR, and local dashcam suites into `.runtime/cache/benchmark/manifests/local/official/` and `.runtime/cache/benchmark/suites/official/`.

Generate the official public gates with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\scripts\prepare_official_public_benchmarks.py --uc3m-split test
```

That workflow turns the public runtime-cache-only sources into first-class official suites:

- `ccpd-readable-ocr`
- `uc3m-readable-ocr`

CCPD is downloaded through the Hugging Face cache under `.runtime/cache/benchmark/cache/hf-hub/`. UC3M-LP is accessed through HTTP range requests and only the selected benchmark images are materialized under `.runtime/cache/benchmark/datasets/official/`.

After preparation, validate or run any official suite from the repo root with the benchmark tool:

```powershell
traffic-lpr-runtime\.venv\Scripts\python.exe traffic-lpr-benchmark\cli.py doctor --suite .runtime\cache\benchmark\suites\official\ccpd-readable-ocr.json
traffic-lpr-runtime\.venv\Scripts\python.exe traffic-lpr-benchmark\cli.py run --suite .runtime\cache\benchmark\suites\official\ccpd-readable-ocr.json --run-id official-ccpd-readable-ocr
```

## Legacy and Exploratory Flows

The following generators still exist, but they are no longer the main official gate pipeline:

- `prepare_public_benchmark.py`: one-off checked-in CCPD hard-case manifest generation
- `prepare_multisource_benchmark.py`: ad hoc mixed-source manifests and development / holdout / challenge slicing

Use these when exploring new mixes or comparing ideas. Use the official generators when you need the maintained benchmark gates that map cleanly onto the dataset catalog and suite catalog.