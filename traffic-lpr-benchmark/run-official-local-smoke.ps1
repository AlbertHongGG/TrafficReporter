param(
  [string]$RunId = $("official-local-smoke-gated-" + (Get-Date -Format 'yyMMdd-HHmmss'))
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$runtimeRoot = Join-Path $repoRoot 'traffic-lpr-runtime'
$runtimePython = Join-Path $runtimeRoot '.venv\Scripts\python.exe'
$suitePath = Join-Path $repoRoot '.runtime\cache\benchmark\suites\official\official-local-smoke.json'

if (-not (Test-Path $runtimePython)) {
  throw "Runtime python was not found: $runtimePython"
}

if (-not (Test-Path $suitePath)) {
  throw "Official local smoke suite was not found: $suitePath"
}

& $runtimePython (Join-Path $scriptRoot 'cli.py') run `
  --suite $suitePath `
  --runtime-root $runtimeRoot `
  --python $runtimePython `
  --run-id $RunId `
  --min-exact-rate 0.75 `
  --min-top3-rate 1.0 `
  --max-mean-cer 0.05 `
  --max-review-required-rate 0.50 `
  --max-no-candidate-rate 0.0 `
  --min-plate-iou 0.90 `
  --max-p95-latency-ms 15000