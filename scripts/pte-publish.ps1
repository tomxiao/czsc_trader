[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^v[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?$')]
    [string]$Tag,
    [switch]$OfflineUpgrade
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$BuildRoot = Join-Path $RepoRoot '.build\pte'
$ProductionRoot = 'D:\CZSC-PTE'
$BuildRelease = Join-Path $BuildRoot "releases\$Tag"
$BuildManifestPath = Join-Path $BuildRelease 'build-manifest.json'
$RuntimeRelease = Join-Path $ProductionRoot "releases\$Tag"
$RuntimeManifestPath = Join-Path $RuntimeRelease 'release-manifest.json'

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python is missing: $Python"
}
if (-not (Test-Path -LiteralPath $BuildManifestPath -PathType Leaf)) {
    throw "PTE build is missing: $BuildManifestPath"
}
$Uv = (Get-Command uv -CommandType Application -ErrorAction Stop).Source
$BuildManifest = Get-Content -LiteralPath $BuildManifestPath -Raw | ConvertFrom-Json
$TagType = (& git -C $RepoRoot cat-file -t $Tag).Trim()
if ($LASTEXITCODE -ne 0 -or $TagType -ne 'tag') {
    throw "PTE publication requires an annotated tag: $Tag"
}
$TagCommit = (& git -C $RepoRoot rev-list -n 1 $Tag).Trim()
if ($LASTEXITCODE -ne 0 -or $BuildManifest.release_id -ne $Tag) {
    throw "PTE build identity differs from requested tag: $Tag"
}
if ($BuildManifest.git_commit -ne $TagCommit) {
    throw "PTE build commit differs from tag $Tag"
}

function Test-PteReleaseHealthy {
    try {
        $Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/health' -TimeoutSec 2
        return ($Health.runtime -eq 'RUNNING' -and $Health.watchdog_healthy -eq $true -and
            $Health.release.release_id -eq $Tag -and $Health.release.git_commit -eq $TagCommit)
    }
    catch {
        return $false
    }
}

Push-Location $RepoRoot
try {
    if (Test-Path -LiteralPath $RuntimeRelease -PathType Container) {
        if (-not (Test-Path -LiteralPath $RuntimeManifestPath -PathType Leaf)) {
            throw "Existing PTE runtime release is incomplete: $RuntimeRelease"
        }
        $RuntimeManifest = Get-Content -LiteralPath $RuntimeManifestPath -Raw |
            ConvertFrom-Json
        if ($RuntimeManifest.release_id -ne $Tag -or
            $RuntimeManifest.git_commit -ne $BuildManifest.git_commit) {
            throw "Existing PTE runtime release differs from build $Tag"
        }
        if ($RuntimeManifest.strategy_snapshot_sha256 -ne
            $BuildManifest.strategy_snapshot_sha256) {
            throw "Existing PTE runtime strategy snapshot differs from build $Tag"
        }
        foreach ($Artifact in $BuildManifest.artifacts.PSObject.Properties) {
            if ($RuntimeManifest.artifacts.($Artifact.Name) -ne $Artifact.Value) {
                throw "Existing PTE runtime artifact differs: $($Artifact.Name)"
            }
        }
        Write-Host "PTE runtime release already installed and matches build: $Tag"
    }
    else {
        & $Python -m paper_trading_engine.release_cli publish `
            --build-root $BuildRoot `
            --runtime-root $ProductionRoot `
            --release $Tag `
            --python $Python `
            --uv $Uv
        if ($LASTEXITCODE -ne 0) {
            throw "PTE publication failed for $Tag with exit code $LASTEXITCODE"
        }
    }

    $ReleaseCli = Join-Path $RuntimeRelease '.venv\Scripts\pte-release.exe'
    if (-not (Test-Path -LiteralPath $ReleaseCli -PathType Leaf)) {
        throw "Published PTE release CLI is missing: $ReleaseCli"
    }
    $AlreadyRunning = $false
    if ($OfflineUpgrade) {
        $AlreadyRunning = Test-PteReleaseHealthy
        if (-not $AlreadyRunning) {
            $ServiceName = 'CZSC-PTE-Watchdog'
            Stop-Service -Name $ServiceName -NoWait
            (Get-Service -Name $ServiceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
            & $ReleaseCli migrate-database --runtime-root $ProductionRoot --release $Tag
            if ($LASTEXITCODE -ne 0) {
                throw "PTE offline database migration failed for $Tag"
            }
        }
    }
    & $ReleaseCli verify `
        --runtime-root $ProductionRoot `
        --release $Tag
    if ($LASTEXITCODE -ne 0) {
        throw "PTE publication preflight failed for $Tag with exit code $LASTEXITCODE"
    }

    if ($OfflineUpgrade) {
        if (-not $AlreadyRunning) {
            & $ReleaseCli activate --runtime-root $ProductionRoot --release $Tag
            if ($LASTEXITCODE -ne 0) {
                throw "PTE activation failed for $Tag"
            }
            Start-Service -Name $ServiceName
            $Deadline = [DateTime]::UtcNow.AddSeconds(60)
            do {
                if (Test-PteReleaseHealthy) {
                    Write-Host "PTE release is active and healthy: $Tag"
                    return
                }
                Start-Sleep -Seconds 1
            } while ([DateTime]::UtcNow -lt $Deadline)
            throw "PTE release did not become healthy after offline upgrade: $Tag"
        }
        Write-Host "PTE release is already active and healthy: $Tag"
        return
    }

    $ActivePath = Join-Path $ProductionRoot 'shared\config\active-release.json'
    if (Test-Path -LiteralPath $ActivePath -PathType Leaf) {
        $Active = Get-Content -LiteralPath $ActivePath -Raw | ConvertFrom-Json
        if ($Active.release_id -eq $Tag) {
            & $ReleaseCli status --runtime-root $ProductionRoot
            if ($LASTEXITCODE -ne 0) {
                throw "PTE active release validation failed for $Tag"
            }
            Write-Host "PTE release is already active: $Tag"
            return
        }
    }

    & $ReleaseCli deploy `
        --runtime-root $ProductionRoot `
        --release $Tag `
        --wait 60 `
        --host 127.0.0.1 `
        --port 8080
    if ($LASTEXITCODE -ne 0) {
        throw "PTE deployment failed for $Tag with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
