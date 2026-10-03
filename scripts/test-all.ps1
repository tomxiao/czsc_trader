[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Node = (Get-Command node -CommandType Application -ErrorAction Stop |
    Select-Object -First 1).Source
$RunId = [guid]::NewGuid().ToString('N')
$RunRoot = Join-Path $RepoRoot ".tmp\test-regression\run-$RunId"
$PytestRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $RepoRoot '.tmp\pytest')
)

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python is missing: $Python"
}
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null

$LaneNames = @('TDR_FREEZE', 'TDR', 'PTE', 'PACKAGES')
$Jobs = @()
$Results = @()
$Total = [System.Diagnostics.Stopwatch]::StartNew()

try {
    foreach ($LaneName in $LaneNames) {
        $LogPath = Join-Path $RunRoot "$($LaneName.ToLowerInvariant()).log"
        $Jobs += Start-Job -Name "czsc-test-$LaneName-$RunId" -ArgumentList @(
            $LaneName, $RepoRoot, $Python, $Node, $LogPath, $RunId
        ) -ScriptBlock {
            param($LaneName, $RepoRoot, $Python, $Node, $LogPath, $RunId)

            Set-StrictMode -Version Latest
            $ErrorActionPreference = 'Stop'
            Set-Location $RepoRoot
            # Prevent NumPy/BLAS inside each pytest process from multiplying the
            # four repository-level workers into dozens of competing threads.
            $env:OMP_NUM_THREADS = '1'
            $env:OPENBLAS_NUM_THREADS = '1'
            $env:MKL_NUM_THREADS = '1'
            $env:NUMEXPR_NUM_THREADS = '1'
            # Tests use fresh bytecode paths per process; writing those throwaway
            # caches adds disk contention without benefiting another test run.
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $env:CZSC_PYTEST_RUN_ID = "$RunId-$LaneName"

            $Steps = [System.Collections.Generic.List[object]]::new()
            if ($LaneName -in @('TDR_FREEZE', 'TDR')) {
                # Keep the shared research fixtures together. The other lane
                # discovers all remaining tests, including newly added files.
                $FreezeTests = @(
                    'tests/functional/test_candidate_freeze.py',
                    'tests/functional/test_assessment_delivery.py'
                )
                $TestSelection = if ($LaneName -eq 'TDR_FREEZE') {
                    $FreezeTests
                }
                else {
                    @('tests') + @($FreezeTests | ForEach-Object { "--ignore=$_" })
                }
                $Steps.Add([pscustomobject]@{
                    Label = $LaneName
                    Executable = $Python
                    Arguments = @(
                        '-m', 'pytest', '-c', 'pyproject.toml', '-q', '--durations=5', '--release-acceptance'
                    ) + $TestSelection
                })
            }
            elseif ($LaneName -eq 'PTE') {
                $Steps.Add([pscustomobject]@{
                    Label = 'PTE'
                    Executable = $Python
                    Arguments = @(
                        '-m', 'pytest', '-c', 'pyproject.toml',
                        'packages\paper_trading_engine\tests', '-q', '--durations=5', '--release-acceptance'
                    )
                })
                $Steps.Add([pscustomobject]@{
                    Label = 'PTE_CONSOLE'
                    Executable = $Node
                    Arguments = @(
                        '--test-isolation=none', '--test', '--test-reporter=tap',
                        'packages\paper_trading_engine\tests\functional\console_state.test.mjs'
                    )
                })
            }
            elseif ($LaneName -eq 'PACKAGES') {
                foreach ($Suite in @(
                    [pscustomobject]@{Label = 'DFLS'; Path = 'packages\dataflows\tests'},
                    [pscustomobject]@{Label = 'FSC'; Path = 'packages\factor_signal_catalog\tests'},
                    [pscustomobject]@{Label = 'STC'; Path = 'packages\strategy_template_catalog\tests'},
                    [pscustomobject]@{Label = 'SM'; Path = 'packages\strategy_manager\tests'},
                    [pscustomobject]@{Label = 'REX'; Path = 'packages\research_experiment\tests'},
                    [pscustomobject]@{Label = 'SE'; Path = 'packages\strategy_evaluator\tests'},
                    [pscustomobject]@{Label = 'SRT'; Path = 'packages\strategy_runtime\tests'},
                    [pscustomobject]@{Label = 'TXE'; Path = 'packages\trading_execution_engine\tests'}
                )) {
                    $Steps.Add([pscustomobject]@{
                        Label = $Suite.Label
                        Executable = $Python
                        Arguments = @(
                            '-m', 'pytest', '-c', 'pyproject.toml', $Suite.Path, '-q',
                            '--durations=5', '--release-acceptance'
                        )
                    })
                }
            }
            else {
                throw "Unknown test lane: $LaneName"
            }

            $Failures = [System.Collections.Generic.List[string]]::new()
            $LaneTimer = [System.Diagnostics.Stopwatch]::StartNew()
            foreach ($Step in $Steps) {
                Add-Content -LiteralPath $LogPath -Encoding utf8 -Value (
                    "===== {0} =====" -f $Step.Label
                )
                $StepTimer = [System.Diagnostics.Stopwatch]::StartNew()
                try {
                    $Output = & $Step.Executable @($Step.Arguments) 2>&1
                    $ExitCode = $LASTEXITCODE
                }
                catch {
                    $Output = $_
                    $ExitCode = 1
                }
                $StepTimer.Stop()
                if ($null -ne $Output) {
                    Add-Content -LiteralPath $LogPath -Encoding utf8 -Value (
                        $Output | Out-String
                    )
                }
                Add-Content -LiteralPath $LogPath -Encoding utf8 -Value (
                    "RESULT {0} EXIT={1} SECONDS={2:N2}" -f
                    $Step.Label, $ExitCode, $StepTimer.Elapsed.TotalSeconds
                )
                if ($ExitCode -ne 0) {
                    $Failures.Add($Step.Label)
                }
            }
            $LaneTimer.Stop()
            [pscustomobject]@{
                Lane = $LaneName
                ExitCode = [int]($Failures.Count -gt 0)
                Seconds = $LaneTimer.Elapsed.TotalSeconds
                Failures = $Failures -join ','
                LogPath = $LogPath
            }
        }
    }

    $Jobs | Wait-Job | Out-Null
    foreach ($LaneName in $LaneNames) {
        $Job = $Jobs | Where-Object { $_.Name -like "czsc-test-$LaneName-*" }
        $Received = @(Receive-Job -Job $Job)
        if ($Job.State -ne 'Completed' -or $Received.Count -ne 1) {
            $Results += [pscustomobject]@{
                Lane = $LaneName
                ExitCode = 1
                Seconds = 0.0
                Failures = "job state $($Job.State)"
                LogPath = Join-Path $RunRoot "$($LaneName.ToLowerInvariant()).log"
            }
        }
        else {
            $Results += $Received[0]
        }
    }
}
finally {
    $Jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    foreach ($LaneName in $LaneNames) {
        $Target = Join-Path $PytestRoot "run-$RunId-$LaneName"
        $ResolvedTarget = [System.IO.Path]::GetFullPath($Target)
        $ExpectedPrefix = $PytestRoot.TrimEnd('\') + '\'
        if (-not $ResolvedTarget.StartsWith(
            $ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Unsafe pytest cleanup target: $ResolvedTarget"
        }
        for ($Attempt = 0; $Attempt -lt 5 -and
            (Test-Path -LiteralPath $ResolvedTarget); $Attempt++) {
            Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force `
                -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $ResolvedTarget) {
                Start-Sleep -Milliseconds 100
            }
        }
        if (Test-Path -LiteralPath $ResolvedTarget) {
            throw "Cannot clean pytest workspace: $ResolvedTarget"
        }
    }
}

foreach ($Result in $Results) {
    Write-Host "===== LANE $($Result.Lane) ====="
    if (Test-Path -LiteralPath $Result.LogPath -PathType Leaf) {
        Get-Content -LiteralPath $Result.LogPath
    }
    Write-Host (
        "LANE_RESULT {0} EXIT={1} SECONDS={2:N2} FAILURES={3}" -f
        $Result.Lane, $Result.ExitCode, $Result.Seconds, $Result.Failures
    )
}

Write-Host '===== RUFF ====='
$RuffTimer = [System.Diagnostics.Stopwatch]::StartNew()
& $Python -m ruff check `
    src tests packages\factor_signal_catalog packages\strategy_template_catalog `
    packages\strategy_manager packages\research_experiment `
    packages\strategy_evaluator packages\dataflows `
    packages\strategy_runtime packages\trading_execution_engine `
    packages\paper_trading_engine\src packages\paper_trading_engine\tests
$RuffExit = $LASTEXITCODE
$RuffTimer.Stop()
Write-Host (
    "RESULT RUFF EXIT={0} SECONDS={1:N2}" -f
    $RuffExit, $RuffTimer.Elapsed.TotalSeconds
)

$Total.Stop()
$FailedLanes = @($Results | Where-Object { $_.ExitCode -ne 0 })
Write-Host "TEST_LOG_ROOT=$RunRoot"
Write-Host ("TOTAL_SECONDS={0:N2}" -f $Total.Elapsed.TotalSeconds)
if ($FailedLanes.Count -gt 0 -or $RuffExit -ne 0) {
    exit 1
}
Write-Host 'FULL_OFFLINE_REGRESSION=PASS'
