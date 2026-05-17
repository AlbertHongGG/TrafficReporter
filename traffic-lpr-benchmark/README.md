# Traffic LPR Benchmark Tool

This folder is the independent benchmark system for the repository. It is intentionally outside the desktop app and outside the Python runtime package so benchmark planning, validation, runs, and reports can evolve on their own boundary.

## Current scope

- benchmark workspace bootstrap
- legacy manifest import
- suite validation
- compact suite inspection
- runtime-backed suite execution
- resumable progress/checkpoint execution
- threshold gate evaluation for exact/top3/CER/IoU/latency
- standalone HTML/JSON/analysis report output
- cross-profile sweep comparison output
- benchmark tool unit tests

## Commands

```powershell
python traffic-lpr-benchmark/cli.py init-workspace
python traffic-lpr-benchmark/cli.py import-legacy-manifest --manifest traffic-lpr-runtime/benchmarks/manifests/templates/sample-manifest.json --suite-id sample-template --output .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py validate --suite .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py doctor --suite .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py print-summary --suite .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py import-legacy-manifest --manifest traffic-lpr-runtime/.runtime/benchmarks/manifests/local/smoke/all.json --suite-id smoke-one --limit 1 --output .runtime/benchmark-tool/suites/smoke-one.json
python traffic-lpr-benchmark/cli.py run --suite .runtime/benchmark-tool/suites/smoke-one.json
python traffic-lpr-benchmark/cli.py run --suite .runtime/benchmark-tool/suites/smoke-one.json --run-id smoke-gate --min-exact-rate 1.0 --min-top3-rate 1.0 --max-mean-cer 0.0 --min-plate-iou 1.0 --max-p95-latency-ms 60000
python traffic-lpr-benchmark/cli.py run --suite .runtime/benchmark-tool/suites/smoke-one.json --run-id smoke-gate --resume
python traffic-lpr-benchmark/cli.py profile-sweep --suite .runtime/benchmark-tool/suites/smoke-one.json --profiles balanced precision recovery
```

From the repo root you can also use the dedicated entrypoint:

```powershell
npm run benchmark -- validate --suite .runtime/benchmark-tool/suites/sample-template.json
npm run benchmark -- doctor --suite .runtime/benchmark-tool/suites/sample-template.json
npm run benchmark -- run --suite .runtime/benchmark-tool/suites/smoke-one.json
npm run benchmark -- profile-sweep --suite .runtime/benchmark-tool/suites/smoke-one.json --profiles balanced precision recovery
npm run benchmark:test
```

## Run Outputs

Each benchmark run now writes the following files under `.runtime/benchmark-tool/runs/<run-id>/`:

- `progress.json`: live execution status updated after each case
- `checkpoint.json`: resumable partial results for `--resume`
- `result.json`: validated benchmark run bundle
- `summary.md`: compact run summary
- `analysis.json`: dataset / split / category / failure-source breakdown
- `analysis.md`: human-readable Taiwan-first benchmark interpretation
- `report.html`: per-case HTML report
- `gate.json`: threshold checks when gate options are supplied

`run` is now suitable for longer suites because it can expose progress, preserve resumable checkpoints, and fail the command when gate thresholds are not met.

`profile-sweep` is the intended Phase 3 / Phase 4 comparison entrypoint: it runs the same suite across multiple analysis profiles and writes a comparison markdown / JSON pair under `.runtime/benchmark-tool/reports/`.

## Layout

- `../schemas/`: repo-level source-of-truth schemas for benchmark suites, run bundles, and shared LPR profile catalogs
- `traffic-lpr-benchmark/`: independent tool code
- `.runtime/benchmark-tool/suites/`: validated suite definitions
- `.runtime/benchmark-tool/runs/`: benchmark run outputs
- `.runtime/benchmark-tool/reports/`: generated reports
- `.runtime/benchmark-tool/imports/`: imported or intermediate artifacts

## Why `doctor` exists

`validate` answers only one question: does the suite match the schema and rule set.

`doctor` answers the operational questions before a real run:

- do all `sourcePath` files actually exist
- what is the case mix by mode / dataset / category
- is the suite mostly local data, public data, or a mix

That keeps benchmark diagnosis inside the same tool boundary instead of pushing more ad hoc shell checks into the repo.
