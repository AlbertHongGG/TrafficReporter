$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$runtimePython = Join-Path $repoRoot 'traffic-lpr-runtime\.venv\Scripts\python.exe'
if (Test-Path $runtimePython) {
  & $runtimePython (Join-Path $scriptRoot 'cli.py') @args
} else {
  python (Join-Path $scriptRoot 'cli.py') @args
}
