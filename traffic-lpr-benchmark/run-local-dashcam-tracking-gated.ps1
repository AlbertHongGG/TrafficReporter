param(
  [string]$RunId = $("local-dashcam-tracking-gated-" + (Get-Date -Format 'yyMMdd-HHmmss'))
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$runtimeRoot = Join-Path $repoRoot 'traffic-lpr-runtime'
$runtimePython = Join-Path $runtimeRoot '.venv\Scripts\python.exe'
$suitePath = Join-Path $repoRoot '.runtime\cache\benchmark\suites\official\local-dashcam-tracking.json'

if (-not (Test-Path $runtimePython)) {
  throw "Runtime python was not found: $runtimePython"
}

if (-not (Test-Path $suitePath)) {
  throw "Local dashcam tracking suite was not found: $suitePath"
}

& $runtimePython (Join-Path $scriptRoot 'cli.py') run `
  --suite $suitePath `
  --runtime-root $runtimeRoot `
  --python $runtimePython `
  --run-id $RunId `
  --min-exact-rate 1.0 `
  --min-top3-rate 1.0 `
  --max-review-required-rate 0.0 `
  --max-no-candidate-rate 0.0 `
  --min-accepted-under-degraded-tracking-rate 1.0 `
  --max-detection-fallback-review-required-rate 0.0 `
  --max-p95-latency-ms 18000