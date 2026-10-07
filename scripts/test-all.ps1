[CmdletBinding()]
param(
    [ValidateRange(1, 8)]
    [int]$MaxParallel = 8
)

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

$LaneNames = @(
    'TDR_FREEZE', 'PTE_2', 'PTE_1', 'DFLS',
    'TDR_2', 'TDR_1', 'TDR_RUNTIME', 'PACKAGES'
)
$Jobs = @()
$Results = @()
$Total = [System.Diagnostics.Stopwatch]::StartNew()

try {
    foreach ($LaneName in $LaneNames) {
        # Start longer groups first and bound the number of active lane jobs.
        $Running = @($Jobs | Where-Object { $_.State -in @('Running', 'NotStarted') })
        while ($Running.Count -ge $MaxParallel) {
            $Running | Wait-Job -Any | Out-Null
            $Running = @($Jobs | Where-Object { $_.State -in @('Running', 'NotStarted') })
        }
        $LogPath = Join-Path $RunRoot "$($LaneName.ToLowerInvariant()).log"
        $Jobs += Start-Job -Name "czsc-test-$LaneName-$RunId" -ArgumentList @(
            $LaneName, $RepoRoot, $Python, $Node, $LogPath, $RunId
        ) -ScriptBlock {
            param($LaneName, $RepoRoot, $Python, $Node, $LogPath, $RunId)

            Set-StrictMode -Version Latest
            $ErrorActionPreference = 'Stop'
            Set-Location $RepoRoot
            # Prevent NumPy/BLAS inside each pytest process from multiplying the
            # repository-level workers into dozens of competing threads.
            $env:OMP_NUM_THREADS = '1'
            $env:OPENBLAS_NUM_THREADS = '1'
            $env:MKL_NUM_THREADS = '1'
            $env:NUMEXPR_NUM_THREADS = '1'
            # Tests use fresh bytecode paths per process; writing those throwaway
            # caches adds disk contention without benefiting another test run.
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $env:CZSC_PYTEST_RUN_ID = "$RunId-$LaneName"

            $Steps = [System.Collections.Generic.List[object]]::new()
            # Keep complete files and their process-local seeds together.
            $RuntimeTests = @(
                'tests/functional/test_candidate_runtime_execution.py',
                'tests/functional/test_srt_backtest_bridge.py',
                'tests/functional/test_evaluation_batch.py',
                'tests/functional/test_input_binding_integrity.py'
            )
            $FreezeTests = @(
                'tests/functional/test_candidate_freeze.py',
                'tests/functional/test_assessment_delivery.py'
            )
            # One explicit group balances the measured expensive files; the
            # other discovers the remainder, including future test files.
            $TdrGroupOne = @(
                'tests/functional/test_research_contract_upgrade.py',
                'tests/functional/test_benchmark_contract.py',
                'tests/functional/test_benchmark_lot_size.py',
                'tests/functional/test_delivery_v2.py',
                'tests/functional/test_research_delivery.py',
                'tests/functional/test_current_contracts.py',
                'tests/functional/test_evaluation.py',
                'tests/functional/test_public_backtest_api.py',
                'tests/functional/test_temp_workspace.py'
            )
            $PteGroupOne = @(
                'packages/paper_trading_engine/tests/functional/test_srt_advice_client.py',
                'packages/paper_trading_engine/tests/functional/test_release_runtime.py',
                'packages/paper_trading_engine/tests/functional/test_account_binding.py',
                'packages/paper_trading_engine/tests/functional/test_account_retirement.py',
                'packages/paper_trading_engine/tests/functional/test_watchdog_service.py',
                'packages/paper_trading_engine/tests/functional/test_web_console.py',
                'packages/paper_trading_engine/tests/functional/test_scheduler.py',
                'packages/paper_trading_engine/tests/functional/test_service_host_isolation.py'
            )
            if ($LaneName -in @('TDR_FREEZE', 'TDR_1', 'TDR_2', 'TDR_RUNTIME', 'DFLS', 'PTE_1', 'PTE_2')) {
                $TestSelection = switch ($LaneName) {
                    'TDR_FREEZE' { $FreezeTests }
                    'TDR_1' { $TdrGroupOne }
                    'TDR_2' {
                        @('tests') + @(
                            ($FreezeTests + $RuntimeTests + $TdrGroupOne) |
                                ForEach-Object { "--ignore=$_" }
                        )
                    }
                    'TDR_RUNTIME' { $RuntimeTests }
                    'DFLS' { 'packages/dataflows/tests' }
                    'PTE_1' { $PteGroupOne }
                    'PTE_2' {
                        @('packages/paper_trading_engine/tests') + @(
                            $PteGroupOne | ForEach-Object { "--ignore=$_" }
                        )
                    }
                }
                $Steps.Add([pscustomobject]@{
                    Label = $LaneName
                    Executable = $Python
                    Arguments = @(
                        '-m', 'pytest', '-c', 'pyproject.toml', '-q', '--durations=5', '--release-acceptance'
                    ) + $TestSelection
                })
                if ($LaneName -eq 'PTE_2') {
                    $Steps.Add([pscustomobject]@{
                        Label = 'PTE_CONSOLE'
                        Executable = $Node
                        Arguments = @(
                            '--test-isolation=none', '--test', '--test-reporter=tap',
                            'packages\paper_trading_engine\tests\functional\console_state.test.mjs'
                        )
                    })
                }
            }
            elseif ($LaneName -eq 'PACKAGES') {
                # These independent package directories can share interpreter
                # imports; their conftests and mutable fixtures remain isolated.
                $Steps.Add([pscustomobject]@{
                    Label = 'PACKAGES'
                    Executable = $Python
                    Arguments = @(
                        '-m', 'pytest', '-c', 'pyproject.toml', '-q',
                        '--durations=5', '--release-acceptance',
                        'packages\factor_signal_catalog\tests',
                        'packages\strategy_template_catalog\tests',
                        'packages\strategy_manager\tests',
                        'packages\strategy_evaluator\tests',
                        'packages\strategy_runtime\tests',
                        'packages\trading_execution_engine\tests'
                    )
                })
            }
            else {
                throw "Unknown test lane: $LaneName"
            }

            $Steps | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -LiteralPath (
                Join-Path (Split-Path -Parent $LogPath) "$($LaneName.ToLowerInvariant())-selection.json"
            )

            $Failures = [System.Collections.Generic.List[string]]::new()
            $LaneTimer = [System.Diagnostics.Stopwatch]::StartNew()
            foreach ($Step in $Steps) {
                Add-Content -LiteralPath $LogPath -Encoding utf8 -Value (
                    "===== {0} =====" -f $Step.Label
                )
                $StepTimer = [System.Diagnostics.Stopwatch]::StartNew()
                try {
                    $StepArguments = @($Step.Arguments)
                    if ($Step.Executable -eq $Python) {
                        # Retain per-case timings for subsequent governance;
                        # the full suite still runs with unchanged assertions.
                        $ReportPath = Join-Path (Split-Path -Parent $LogPath) (
                            "$($Step.Label.ToLowerInvariant()).xml"
                        )
                        $StepArguments += "--junitxml=$ReportPath"
                    }
                    $Output = & $Step.Executable @StepArguments 2>&1
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
    packages\strategy_manager `
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
Write-Host "MAX_PARALLEL=$MaxParallel"
Write-Host ("TOTAL_SECONDS={0:N2}" -f $Total.Elapsed.TotalSeconds)
if ($FailedLanes.Count -gt 0 -or $RuffExit -ne 0) {
    exit 1
}
Write-Host 'FULL_OFFLINE_REGRESSION=PASS'
