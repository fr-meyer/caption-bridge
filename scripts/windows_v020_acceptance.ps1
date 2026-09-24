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
        $env:NO_PROXY = '127.0.0.1,localhost,::1'
        $env:no_proxy = $env:NO_PROXY

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

        $currentStage = 'loopback-root-http'
        $rootResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$AppPort/" -TimeoutSec 5
        if ($rootResponse.StatusCode -ne 200) {
            throw 'The exact-release application root did not return HTTP 200.'
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
            '--no-proxy-server',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            "http://127.0.0.1:$AppPort/"
        ) -RedirectStandardOutput $browserOut -RedirectStandardError $browserErr -WindowStyle Hidden -PassThru

        $cdpReady = $false
        $cdpWebSocketUrl = $null
        $cdpDeadline = [DateTime]::UtcNow.AddSeconds(30)
        while ([DateTime]::UtcNow -lt $cdpDeadline) {
            if ($browser.HasExited) {
                break
            }
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$CdpPort/json/version" -TimeoutSec 1
                if ($response.StatusCode -eq 200) {
                    $cdpMetadata = $response.Content | ConvertFrom-Json
                    $candidateWebSocketUrl = [string]$cdpMetadata.webSocketDebuggerUrl
                    if (-not [string]::IsNullOrWhiteSpace($candidateWebSocketUrl)) {
                        $candidateWebSocketUri = [Uri]$candidateWebSocketUrl
                        if (
                            $candidateWebSocketUri.Scheme -eq 'ws' -and
                            $candidateWebSocketUri.Host -in @('127.0.0.1', 'localhost', '::1') -and
                            $candidateWebSocketUri.Port -eq $CdpPort
                        ) {
                            $cdpWebSocketUrl = $candidateWebSocketUrl
                            $cdpReady = $true
                            break
                        }
                    }
                }
            }
            catch {
                Start-Sleep -Milliseconds 200
            }
        }
        if (-not $cdpReady -or [string]::IsNullOrWhiteSpace($cdpWebSocketUrl)) {
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
import time

from websockets.sync.client import connect

app_url = sys.argv[1]
cdp_url = sys.argv[2]

next_id = 0


def call(socket, method, params=None, session_id=None):
    global next_id
    next_id += 1
    payload = {'id': next_id, 'method': method}
    if params is not None:
        payload['params'] = params
    if session_id is not None:
        payload['sessionId'] = session_id
    socket.send(json.dumps(payload, separators=(',', ':')))
    while True:
        response = json.loads(socket.recv(timeout=10))
        if response.get('id') != next_id:
            continue
        if 'error' in response:
            raise RuntimeError('CDP command failed')
        return response.get('result', {})


expression = r'''(() => {
  const controls = ['status-label', 'start-btn', 'idle-target-select'];
  const visible = controls.every((id) => {
    const element = document.getElementById(id);
    if (!element) return false;
    const style = getComputedStyle(element);
    const bounds = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      bounds.width > 0 && bounds.height > 0;
  });
  const status = document.getElementById('status-label');
  const body = document.body;
  const idleState = Boolean(body && ['idle_blocked', 'idle_ready'].includes(body.dataset.state));
  return {
    visible, statusNonempty: Boolean(status && status.textContent.trim()), idleState,
    bodyPresent: Boolean(body), documentComplete: document.readyState === 'complete',
    loopbackPage: location.protocol === 'http:' && location.hostname === '127.0.0.1',
  };
})()'''

phase = 'connect'
target_id = None
session_id = None
navigation_error = 'none'
evaluation_seen = False
evaluation_exception = False
last_value = {}

try:
    with connect(
        cdp_url,
        proxy=None,
        open_timeout=10,
        close_timeout=2,
        ping_interval=None,
    ) as socket:
        phase = 'target_lookup'
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            targets = call(socket, 'Target.getTargets').get('targetInfos', [])
            target_id = next((
                target.get('targetId')
                for target in targets
                if target.get('type') == 'page' and
                str(target.get('url', '')).startswith(app_url)
            ), None)
            if target_id is not None:
                break
            time.sleep(0.1)
        if target_id is None:
            raise RuntimeError('application page missing')

        phase = 'target_attach'
        session_id = call(
            socket,
            'Target.attachToTarget',
            {'targetId': target_id, 'flatten': True},
        ).get('sessionId')
        if not session_id:
            raise RuntimeError('CDP target attach failed')

        phase = 'navigate'
        navigation = call(socket, 'Page.navigate', {'url': app_url}, session_id)
        raw_navigation_error = str(navigation.get('errorText', ''))
        if raw_navigation_error:
            navigation_error = {
                'net::ERR_CONNECTION_REFUSED': 'connection_refused',
                'net::ERR_EMPTY_RESPONSE': 'empty_response',
                'net::ERR_PROXY_CONNECTION_FAILED': 'proxy_connection_failed',
                'net::ERR_BLOCKED_BY_CLIENT': 'blocked_by_client',
                'net::ERR_INVALID_URL': 'invalid_url',
            }.get(raw_navigation_error, 'other')
            raise RuntimeError('application navigation failed')

        phase = 'evaluate'
        deadline = time.monotonic() + 10
        gate_passed = False
        while time.monotonic() < deadline:
            evaluation = call(
                socket,
                'Runtime.evaluate',
                {'expression': expression, 'returnByValue': True},
                session_id,
            )
            value = evaluation.get('result', {}).get('value', {})
            evaluation_seen = True
            evaluation_exception = evaluation_exception or bool(evaluation.get('exceptionDetails'))
            last_value = value if isinstance(value, dict) else {}
            gate_passed = bool(last_value.get('visible') and last_value.get('statusNonempty') and last_value.get('idleState'))
            if gate_passed:
                break
            time.sleep(0.1)
        if not gate_passed:
            phase = 'controls_timeout'
            raise RuntimeError('public controls not ready')
except Exception:
    print(json.dumps({
        'public_dom_gate': 'failed',
        'phase': phase,
        'target_found': bool(target_id),
        'session_attached': bool(session_id),
        'navigation_error': navigation_error,
        'evaluation_seen': evaluation_seen,
        'evaluation_exception': evaluation_exception,
        'body_present': bool(last_value.get('bodyPresent')),
        'document_complete': bool(last_value.get('documentComplete')),
        'loopback_page': bool(last_value.get('loopbackPage')),
        'visible': bool(last_value.get('visible')),
        'status_nonempty': bool(last_value.get('statusNonempty')),
        'idle_state': bool(last_value.get('idleState')),
    }, sort_keys=True), file=sys.stderr)
    raise SystemExit('public DOM gate failed') from None

print(json.dumps({
    'cdp_loopback': True,
    'page_present': True,
    'public_controls_present': True,
}, sort_keys=True))
'@ | Set-Content -LiteralPath $gateScript -Encoding utf8

        $currentStage = 'public-dom-gate'
        $proxyVariables = @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')
        $proxyValues = @{}
        foreach ($proxyName in $proxyVariables) {
            $proxyValues[$proxyName] = [Environment]::GetEnvironmentVariable($proxyName, 'Process')
            [Environment]::SetEnvironmentVariable($proxyName, $null, 'Process')
        }
        try {
            Invoke-NativeGate $python $gateScript "http://127.0.0.1:$AppPort/" $cdpWebSocketUrl
        }
        finally {
            foreach ($proxyName in $proxyVariables) {
                [Environment]::SetEnvironmentVariable($proxyName, $proxyValues[$proxyName], 'Process')
            }
        }
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
