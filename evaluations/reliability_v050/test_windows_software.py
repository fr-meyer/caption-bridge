"""Version-specific Windows contract and real app boot with external IO faked."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from app.identity import PACKAGE_VERSION
from app.lifecycle import LifecycleController, RuntimePaths
from scripts.windows_v050_fixture_app import build_app

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "scripts/windows_v020_acceptance.ps1"
NEW = ROOT / "scripts/windows_v050_software_acceptance.ps1"


def embedded(source):
    start = source.index("        @'\n") + len("        @'\n")
    return source[start : source.index("\n'@ | Set-Content -LiteralPath $gateScript", start)]


def test_current_windows_harness_matches_version_and_preserves_legacy_gate():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    source = NEW.read_text()
    assert version == PACKAGE_VERSION and f"$identity.package_version -ne '{version}'" in source
    assert "$identity.package_version -ne '0.2.0'" in OLD.read_text()
    assert embedded(source) == embedded(OLD.read_text())
    assert (
        "uv python install" not in source
        and "uv sync" not in source
        and "playwright install" not in source
    )
    assert "resilience_soak --segments 1000" not in source
    assert "evaluations/reliability_v050/run_offline.py" in source
    assert "'.venv\\Scripts\\python.exe'" in source
    assert "scripts/windows_v050_fixture_app.py" in source and "'app.main:app'" not in source
    assert "physical_windows_pass = $false" in source and "software-fixture-proof" in source
    assert "ordinary_windows_controller_pass = $false" in source
    assert (
        "Stop-OwnedProcessTree -Process $browser" in source
        and "Stop-OwnedProcessTree -Process $server" in source
    )


def test_windows_receipt_is_content_free_and_success_follows_owned_cleanup():
    source = NEW.read_text()
    assert "[string]$ReceiptPath" in source
    assert "[IO.FileMode]::CreateNew" in source
    assert "Receipt must be a new file outside the source checkout." in source
    assert "source_unchanged -ne $true" in source
    assert source.count('Uri "http://127.0.0.1:$AppPort/software/fixture-proof"') == 2
    assert source.index("$currentStage = 'software-fixture-final-proof'") > source.index(
        "$currentStage = 'public-dom-gate'"
    )
    assert source.index("$summary = [ordered]@{") > source.index(
        "$browserStopped = Stop-OwnedProcessTree"
    )
    summary = source[source.index("$summary = [ordered]@{"):]
    assert "status = if ($gateFailed -or $cleanupFailed)" in summary
    assert "offline = $offlineReceipt" in summary
    assert "source_head = $actualSha" in summary
    assert "fixture = $fixtureProof" in summary
    assert "$currentStage = 'final-software-identity'" in source
    assert "$finalIdentity.git_dirty -ne $false" in source
    assert "serverOut" not in summary and "serverErr" not in summary
    assert "ConvertTo-Json -Depth 8 -Compress" in summary


def test_v050_embedded_dom_gate_uses_the_reviewed_loopback_and_redaction_contract():
    spec = importlib.util.spec_from_file_location(
        "legacy_windows_fixture", ROOT / "tests/unit/test_windows_v020_acceptance_harness.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.SCRIPT = NEW
    case = fixture.WindowsV020AcceptanceHarnessTests()
    case.test_public_dom_gate_checks_idle_controls()
    case.test_raw_cdp_failure_reports_only_bounded_state()


def test_real_application_fixture_lifespan_never_queries_devices_or_providers(tmp_path):
    async def scenario():
        app, calls = build_app(tmp_path, 8776)
        async with app.router.lifespan_context(app):
            from app import main

            await main.poller.evaluate_now()
            assert main.manager.session.status == "idle_blocked"
            assert not main.manager._reliability.pipeline.capture_active
            proof = next(
                route.endpoint
                for route in app.routes
                if getattr(route, "path", None) == "/software/fixture-proof"
            )
            assert await proof() == {
                "software_fixture": True,
                "native_input_enabled": False,
                "native_calls": 0,
                "provider_calls": 0,
                "capture_active": False,
            }
        assert calls == {"native": 0, "provider": 0}

    asyncio.run(asyncio.wait_for(scenario(), 2))


@pytest.mark.xfail(
    strict=True,
    reason="app.lifecycle is Mac/POSIX; Windows Scripts/process ownership remains unsupported",
)
def test_mac_lifecycle_does_not_yet_implement_windows_native_python_path(tmp_path):
    controller = LifecycleController(
        tmp_path, paths=RuntimePaths(tmp_path / "state.json", tmp_path / "log")
    )
    assert controller.python_path == tmp_path / ".venv" / "Scripts" / "python.exe"


@pytest.mark.skipif(
    shutil.which("pwsh") is None,
    reason="PowerShell runtime not installed; no Windows execution claimed",
)
def test_powershell_ast_parse_only():
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            "$tokens=$null;$errors=$null;[System.Management.Automation.Language.Parser]::ParseFile($env:CAPTION_PS_AST_SOURCE,[ref]$tokens,[ref]$errors)|Out-Null;if($errors.Count){exit 1}",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        env=dict(os.environ, CAPTION_PS_AST_SOURCE=str(NEW)),
    )
    assert result.returncode == 0
