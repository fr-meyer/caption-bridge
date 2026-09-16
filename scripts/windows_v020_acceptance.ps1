[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedSha,

    [ValidateRange(1, 65535)]
    [int]$AppPort = 8765,

    [ValidateRange(1, 65535)]
    [int]$CdpPort = 9229
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $true
}

function Invoke-NativeGate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'A deterministic acceptance command failed.'
    }
}

function Stop-OwnedProcessTree {
    param([System.Diagnostics.Process]$Process)

    if ($null -eq $Process) {
        return
    }
    try {
        if (-not $Process.HasExited) {
            & taskkill.exe /PID $Process.Id /T /F *> $null
        }
    }
    catch {
        # The final listener check is the authoritative teardown gate.
    }
}

function Get-BoundListeners {
    param([int[]]$Ports)

    return @(
        Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -in $Ports }
    )
}

$repo = (Resolve-Path -LiteralPath $RepoRoot).Path
$runnerTemp = [Environment]::GetEnvironmentVariable('RUNNER_TEMP')
if ([string]::IsNullOrWhiteSpace($runnerTemp)) {
    throw 'RUNNER_TEMP is required for isolated acceptance state.'
}
if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('MISTRAL_API_KEY'))) {
    throw 'Provider credentials must not be present in the hosted acceptance job.'
}
if ($AppPort -eq $CdpPort) {
    throw 'Application and CDP ports must differ.'
}

$runtimeRoot = Join-Path $runnerTemp 'caption-bridge-v020-acceptance'
$profileRoot = Join-Path $runtimeRoot 'chromium-profile'
$serverOut = Join-Path $runtimeRoot 'server.stdout'
$serverErr = Join-Path $runtimeRoot 'server.stderr'
$browserOut = Join-Path $runtimeRoot 'browser.stdout'
$browserErr = Join-Path $runtimeRoot 'browser.stderr'
$gateScript = Join-Path $runtimeRoot 'dom_gate.py'
$server = $null
$browser = $null
$gateFailed = $false
$cleanupFailed = $false
$currentStage = 'preflight'
$failureStage = 'unknown'

try {
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Push-Location $repo
    try {
        $actualSha = (git rev-parse HEAD).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0 -or $actualSha -ne $ExpectedSha.ToLowerInvariant()) {
            throw 'The checked-out release does not match the immutable expected SHA.'
        }
        if (@(git status --porcelain=v1).Count -ne 0) {
            throw 'The exact-release checkout is not clean.'
        }

        $currentStage = 'install-python'
        Invoke-NativeGate uv python install 3.13
        $currentStage = 'sync-locked-dependencies'
        Invoke-NativeGate uv sync --frozen --python 3.13

        $currentStage = 'provider-free-software-identity'
        $identity = Invoke-NativeGate uv run --python 3.13 python -m app.identity --json |
            Select-Object -Last 1 |
            ConvertFrom-Json
        if (
            $identity.service -ne 'caption-bridge' -or
            $identity.package_version -ne '0.2.0' -or
            $identity.git_sha.ToLowerInvariant() -ne $ExpectedSha.ToLowerInvariant() -or
            $identity.git_dirty -ne $false
        ) {
            throw 'Runtime identity does not match the immutable release.'
        }
        Write-Output '{"exact_release":true,"provider_configuration":false,"software_identity":true}'

        $currentStage = 'deterministic-validation'
        Invoke-NativeGate uv run --python 3.13 ruff check .
        Invoke-NativeGate uv run --python 3.13 python -m scripts.benchmark_translation_quality --max-false-positive-rate 0.05 --min-recall 1.0 --require-exact-reasons
        Invoke-NativeGate uv run --python 3.13 python -m scripts.benchmark_segmentation --max-unexpected-standalone 0 --max-delayed-clear 0 --max-policy-delay-ms 4500 --json
        Invoke-NativeGate uv run --python 3.13 python -m scripts.resilience_soak --segments 1000 --json
        Invoke-NativeGate uv run --python 3.13 python -m scripts.full_pipeline_scenario --json
        Invoke-NativeGate uv run --python 3.13 python -m pytest -q
        Invoke-NativeGate node --check app/static/app.js
        $currentStage = 'install-managed-chromium'
        Invoke-NativeGate uv run --python 3.13 python -m playwright install chromium
        $currentStage = 'browser-tests'
        Invoke-NativeGate uv run --python 3.13 python -m pytest -q browser_tests --browser chromium

        $currentStage = 'controller-idle-preflight'
        $controllerStatus = Invoke-NativeGate uv run --python 3.13 python -m scripts.caption_bridge_ctl status --json | ConvertFrom-Json
        if ($controllerStatus.status -ne 'stopped' -or $controllerStatus.running -ne $false) {
            throw 'The clean Windows controller state is not stopped.'
        }

        $python = Join-Path $repo '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            throw 'The locked Windows virtual environment is incomplete.'
        }

        $env:HOST = '127.0.0.1'
        $env:PORT = $AppPort.ToString()
        $env:MISTRAL_TTS_ENABLED = 'false'
        $env:JOURNAL_DIR = Join-Path $runtimeRoot 'journal'
        $env:RECOVERY_EXPORT_DIR = Join-Path $runtimeRoot 'recovered'
        $env:RELIABILITY_DIR = Join-Path $runtimeRoot 'reliability'
        $env:EXPORT_DIR = Join-Path $runtimeRoot 'exports'

        $currentStage = 'loopback-server-health'
        $server = Start-Process -FilePath $python -ArgumentList @(
            '-m', 'uvicorn', 'app.main:app',
            '--host', '127.0.0.1',
            '--port', $AppPort.ToString(),
            '--log-level', 'warning'
        ) -WorkingDirectory $repo -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr -WindowStyle Hidden -PassThru

        $healthReady = $false
        $healthDeadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $healthDeadline) {
            if ($server.HasExited) {
                break
            }
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$AppPort/healthz" -TimeoutSec 1
                if ($health.service -eq 'caption-bridge' -and $health.status -eq 'ok') {
                    $healthReady = $true
                    break
                }
            }
            catch {
                Start-Sleep -Milliseconds 200
            }
        }
        if (-not $healthReady) {
            throw 'The exact-release loopback health gate did not pass.'
        }

        $browserPath = (& $python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()" | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $browserPath -PathType Leaf)) {
            throw 'The managed Chromium executable is unavailable.'
        }

        $currentStage = 'loopback-browser-cdp'
        $browser = Start-Process -FilePath $browserPath -ArgumentList @(
            '--headless=new',
            '--remote-debugging-address=127.0.0.1',
            "--remote-debugging-port=$CdpPort",
            "--user-data-dir=$profileRoot",
            '--no-first-run',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            "http://127.0.0.1:$AppPort/"
        ) -RedirectStandardOutput $browserOut -RedirectStandardError $browserErr -WindowStyle Hidden -PassThru

        $cdpReady = $false
        $cdpDeadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $cdpDeadline) {
            if ($browser.HasExited) {
                break
            }
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$CdpPort/json/version" -TimeoutSec 1
                if ($response.StatusCode -eq 200) {
                    $cdpReady = $true
                    break
                }
            }
            catch {
                Start-Sleep -Milliseconds 200
            }
        }
        if (-not $cdpReady) {
            throw 'The loopback-only Chromium CDP gate did not become ready.'
        }

        $listeners = Get-BoundListeners -Ports @($AppPort, $CdpPort)
        foreach ($port in @($AppPort, $CdpPort)) {
            if (@($listeners | Where-Object { $_.LocalPort -eq $port }).Count -eq 0) {
                throw 'A required loopback listener is missing.'
            }
        }
        $nonLoopback = @(
            $listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }
        )
        if ($nonLoopback.Count -ne 0) {
            throw 'A required listener is bound beyond loopback.'
        }

        @'
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

app_url = sys.argv[1]
cdp_url = sys.argv[2]
with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    pages = [page for context in browser.contexts for page in context.pages]
    page = next((candidate for candidate in pages if candidate.url.startswith(app_url)), None)
    if page is None:
        raise SystemExit('application page missing')
    page.locator('#status-label').wait_for(state='visible', timeout=10_000)
    page.locator('#start-btn').wait_for(state='visible', timeout=10_000)
    page.locator('#gear-btn').wait_for(state='visible', timeout=10_000)
    if not page.locator('#status-label').inner_text().strip():
        raise SystemExit('public status is empty')
    print(json.dumps({
        'cdp_loopback': True,
        'page_present': True,
        'public_controls_present': True,
    }, sort_keys=True))
'@ | Set-Content -LiteralPath $gateScript -Encoding utf8

        $currentStage = 'public-dom-gate'
        Invoke-NativeGate $python $gateScript "http://127.0.0.1:$AppPort/" "http://127.0.0.1:$CdpPort"
        Write-Output '{"exact_release":true,"windows_runtime":true,"loopback_only":true,"provider_calls":false,"public_dom_gate":true}'
    }
    finally {
        Pop-Location
    }
}
catch {
    $gateFailed = $true
    $failureStage = $currentStage
}
finally {
    Stop-OwnedProcessTree -Process $browser
    Stop-OwnedProcessTree -Process $server
    Start-Sleep -Milliseconds 750

    if (@(Get-BoundListeners -Ports @($AppPort, $CdpPort)).Count -ne 0) {
        $cleanupFailed = $true
    }

    try {
        if (Test-Path -LiteralPath $runtimeRoot) {
            Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
        }
        if (Test-Path -LiteralPath $runtimeRoot) {
            $cleanupFailed = $true
        }
    }
    catch {
        $cleanupFailed = $true
    }
}

if ($cleanupFailed) {
    throw 'Hosted Windows acceptance cleanup failed.'
}
if ($gateFailed) {
    throw "Hosted Windows acceptance failed at stage '$failureStage'; content-bearing diagnostics are intentionally suppressed."
}
Write-Output '{"cleanup":true,"listeners_remaining":0,"temporary_profile_remaining":false}'
