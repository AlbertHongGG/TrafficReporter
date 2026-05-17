# Traffic LPR Benchmark Tool

This folder is the independent benchmark system for the repository. It is intentionally outside the desktop app and outside the Python runtime package so benchmark planning, validation, runs, and reports can evolve on their own boundary.

## Current scope

- benchmark workspace bootstrap
- legacy manifest import
- suite validation
- compact suite inspection
- runtime-backed suite execution
- standalone HTML/JSON report output
- benchmark tool unit tests

## Commands

```powershell
python traffic-lpr-benchmark/cli.py init-workspace
python traffic-lpr-benchmark/cli.py import-legacy-manifest --manifest traffic-lpr-runtime/benchmarks/manifests/templates/sample-manifest.json --suite-id sample-template --output .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py validate --suite .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py print-summary --suite .runtime/benchmark-tool/suites/sample-template.json
python traffic-lpr-benchmark/cli.py import-legacy-manifest --manifest traffic-lpr-runtime/.runtime/benchmarks/manifests/local/smoke/all.json --suite-id smoke-one --limit 1 --output .runtime/benchmark-tool/suites/smoke-one.json
python traffic-lpr-benchmark/cli.py run --suite .runtime/benchmark-tool/suites/smoke-one.json
```

From the repo root you can also use the dedicated entrypoint:

```powershell
npm run benchmark -- validate --suite .runtime/benchmark-tool/suites/sample-template.json
npm run benchmark -- run --suite .runtime/benchmark-tool/suites/smoke-one.json
npm run benchmark:test
```

## Layout

- `schemas/`: repo-level source-of-truth schemas for benchmark suites, run bundles, and shared LPR profile catalogs
- `traffic-lpr-benchmark/`: independent tool code
- `.runtime/benchmark-tool/suites/`: validated suite definitions
- `.runtime/benchmark-tool/runs/`: benchmark run outputs
- `.runtime/benchmark-tool/reports/`: generated reports
- `.runtime/benchmark-tool/imports/`: imported or intermediate artifacts
