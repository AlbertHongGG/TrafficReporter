# Benchmark Notes

Build your benchmark around target-centric hard cases from moving-camera footage.

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
- `analysisOptions`: ablation switches for tracker / fusion / restoration / OCR comparison

Suggested benchmark splits:

- `development`: cases you iterate on every day
- `holdout`: cases you do not inspect while tuning
- `challenge`: worst failure cases that are allowed to be slow but should improve over time

The runtime returns per-case exact match, top-3 match, and character error rate. Use those three together; exact match alone hides whether you are close or far from the right answer.

## Public Dataset Workflow

For a repeatable public hard-case benchmark that does not depend on your own footage, prepare a CCPD-based frame benchmark with:

```powershell
cd traffic-lpr-runtime
.\.venv\Scripts\python.exe benchmarks\prepare_public_benchmark.py --per-category 25
```

The script downloads the public `zenitsu09/ccpd-subset-30k` archive from Hugging Face into `.runtime/public-datasets/hf-cache/`, samples a balanced hard-case mix, extracts only the sampled images into `.runtime/public-datasets/ccpd-hardcases/`, and writes `benchmarks/public-ccpd-hardcases.json`.

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
.\.venv\Scripts\python.exe -m traffic_lpr_runtime benchmark-run < benchmarks\public-ccpd-hardcases.json
```

This public benchmark is image-based, so it measures the OCR, rectification, restoration, and ranking stack on hard cases without overfitting to your own video. Keep interval/video benchmarks separate when you want to evaluate tracker behavior.