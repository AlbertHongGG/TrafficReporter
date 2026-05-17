# Benchmark Notes

Build benchmarks around target-centric hard cases from moving-camera footage.

## Layout

- `benchmarks/scripts/` stores generator entrypoints and shared helpers.
- `benchmarks/manifests/templates/` stores hand-authored templates such as the local sample manifest.
- `benchmarks/manifests/public/` stores committed public benchmark manifests.
- `.runtime/benchmarks/cache/` stores disposable download caches.
- `.runtime/benchmarks/datasets/` stores materialized benchmark images referenced by generated manifests.

Keep only reusable benchmark definitions under `benchmarks/`. Smoke outputs, extracted images, transient downloads, and one-off analysis artifacts belong under `.runtime/` and can be deleted safely.

Recommended annotation fields per case:

- `id`: stable case identifier
- `mode`: `frame` or `interval`
- `sourcePath`: absolute path to the original video
- `interval`: the narrowest useful time window around the target vehicle
- `anchorTimeMs`: frame where the target vehicle is easiest to select
- `selectedTargetBox`: normalized vehicle box on the anchor frame
- `expectedText`: normalized plate text without punctuation
- `countryHints`: `['TW']` for Taiwan-first OCR priors
- `tags`: conditions such as `night`, `blur`, `angle`, `small-plate`, `glare`, `occlusion`, `moving-camera`
- `analysisOptions`: ablation switches for tracker, fusion, restoration, and OCR comparison

Suggested benchmark splits:

- `development`: cases you iterate on every day
- `holdout`: cases you do not inspect while tuning
- `challenge`: worst failure cases that are allowed to be slow but should improve over time

The runtime returns per-case exact match, top-3 match, and character error rate. Use those three together; exact match alone hides whether you are close or far from the right answer.

The benchmark runner now also reports:

- plate / target localization recall and mean IoU when a manifest includes ground-truth boxes
- confidence calibration bins plus expected calibration error
- accepted-candidate margin and p50 / p95 latency
- interval-track stability signals such as prediction switch count, majority-vote exact match, and time-to-first-correct
- failure taxonomy buckets such as `target-missed`, `plate-localization-missed`, `ocr-disagreement`, and `fusion-unstable`

## Public Dataset Workflow

For a repeatable public hard-case benchmark that does not depend on your own footage, prepare a CCPD-based frame benchmark with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\scripts\prepare_public_benchmark.py --per-category 25
```

The script downloads the public `zenitsu09/ccpd-subset-30k` archive from Hugging Face into `.runtime/benchmarks/cache/hf-hub/`, samples a balanced hard-case mix, extracts only the sampled images into `.runtime/benchmarks/datasets/ccpd-hardcases/`, and writes `benchmarks/manifests/public/ccpd-hardcases.json`.

The generated manifest emphasizes these categories:

- `blur`: native `ccpd_blur` samples plus the highest-blur decile
- `angle`: `ccpd_tilt` and `ccpd_rotate`
- `challenge`: `ccpd_challenge`
- `small-plate`: `ccpd_fn`
- `weather`: `ccpd_weather`
- `low-light`: `ccpd_db` plus the darkest brightness decile
- `high-exposure`: the brightest decile

Run the benchmark with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < benchmarks\manifests\public\ccpd-hardcases.json
```

This public benchmark is image-based, so it measures the OCR, rectification, restoration, and ranking stack on hard cases without overfitting to your own video. Keep interval/video benchmarks separate when you want to evaluate tracker behavior.

## Multi-Source Workflow

To reduce China-only bias and keep a second public domain in the loop, build a combined CCPD + UC3M-LP manifest with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\scripts\prepare_multisource_benchmark.py --datasets ccpd uc3m-lp --per-category 20 --uc3m-split test
```

This workflow:

- keeps the existing CCPD hard-case buckets for blur, angle, weather, low-light, and small plates
- adds `UC3M-LP` as a European/Spanish counterweight so public evaluation is not dominated by Chinese plates
- reads the UC3M-LP archive through HTTP range requests instead of requiring a full 4.5 GB download up front
- emits a combined manifest plus three stratified manifests under `benchmarks/manifests/public/multisource/`:
development, holdout, and challenge

The combined output is written to `benchmarks/manifests/public/multisource/all.json`, and sampled images are extracted under `.runtime/benchmarks/datasets/multisource-hardcases/`.

Run the resulting benchmark exactly the same way:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < benchmarks\manifests\public\multisource\all.json
```

Use the split manifests when you want to separate daily iteration from the harder review set:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < benchmarks\manifests\public\multisource\development.json
```

## Local AOLP + UFPR Workflow

When the full local datasets already exist under `datasets/aolp/` and `datasets/ufpr-alpr/`, generate a mixed local benchmark with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\scripts\prepare_multisource_benchmark.py --datasets aolp ufpr-alpr --per-category 12 --ufpr-split testing
```

This local workflow:

- parses AOLP `Subset_AC|LE|RP` images plus localization / recognition text files directly from disk
- preserves AOLP subset identity as `subset-ac`, `subset-le`, and `subset-rp` instead of flattening them into one score
- materializes UFPR tracks into short local interval videos under `.runtime/benchmarks/datasets/local-multisource/ufpr-alpr/tracks/`
- emits machine-local manifests under `.runtime/benchmarks/manifests/local/multisource/`
- writes `groundTruthPlateBox`, `groundTruthTargetBox`, and `groundTruthFrames` into the manifest so `benchmark-run` can score localization and interval stability

Run the resulting suite with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < .runtime\benchmarks\manifests\local\multisource\all.json
```

Recommended usage:

- treat AOLP as the Taiwan-primary OCR / localization gate
- treat UFPR-ALPR as the moving-camera tracking / fusion reliability gate
- compare `development`, `holdout`, and `challenge` manifests separately instead of only watching the merged average

The split manifests are stratified per dataset-and-category group, so they are not expected to be equal-sized thirds. `development` is usually the largest slice, while `challenge` keeps the hardest examples from each group.