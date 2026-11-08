[CmdletBinding()]
param(
    [ValidateRange(1, 12)]
    [int]$MaxParallel = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python is missing: $Python"
}
# Requires spawn-process IPC and local Git permissions; the runner checks them
# before starting any test. All test discovery, coverage and timings are logged.
& $Python (Join-Path $PSScriptRoot 'test_regression.py') --max-parallel $MaxParallel
exit $LASTEXITCODE
