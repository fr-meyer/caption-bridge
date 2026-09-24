from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[2] / "scripts" / "windows_v020_acceptance.ps1"


def embedded_dom_gate_source() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start_marker = "        @'\n"
    end_marker = "\n'@ | Set-Content -LiteralPath $gateScript"
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class WindowsV020AcceptanceHarnessTests(unittest.TestCase):
    def test_hosted_windows_identity_gate_is_provider_free(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("scripts.runtime_preflight", source)
        self.assertNotIn("app.config", source)
        self.assertIn("python -m app.identity --json", source)
        self.assertIn("provider-free-software-identity", source)
        self.assertIn("Provider credentials must not be present", source)
        self.assertIn("$identity.git_dirty -ne $false", source)
        self.assertIn('"provider_configuration":false', source)

    def test_hosted_windows_gate_preserves_stage_only_failure_evidence(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$failureStage = $currentStage", source)
        self.assertIn("failed at stage '$failureStage'", source)
        self.assertIn("content-bearing diagnostics are intentionally suppressed", source)

    def test_loopback_browser_gate_bypasses_hosted_runner_proxies(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$env:NO_PROXY = '127.0.0.1,localhost,::1'", source)
        self.assertIn("$env:no_proxy = $env:NO_PROXY", source)
        self.assertIn("'--no-proxy-server'", source)
        self.assertIn("$proxyVariables = @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')", source)
        self.assertIn("SetEnvironmentVariable($proxyName, $null, 'Process')", source)
        self.assertIn("SetEnvironmentVariable($proxyName, $proxyValues[$proxyName], 'Process')", source)
        self.assertIn("$cdpMetadata.webSocketDebuggerUrl", source)
        self.assertIn("$candidateWebSocketUri.Host -in @('127.0.0.1', 'localhost', '::1')", source)
        self.assertIn("$candidateWebSocketUri.Port -eq $CdpPort", source)
        self.assertIn("$python $gateScript \"http://127.0.0.1:$AppPort/\" $cdpWebSocketUrl", source)
        self.assertIn("from websockets.sync.client import connect", source)
        self.assertIn("proxy=None", source)
        self.assertIn("'Target.getTargets'", source)
        self.assertIn("'Target.attachToTarget'", source)
        self.assertIn("'Runtime.evaluate'", source)
        self.assertIn("raise SystemExit('public DOM gate failed') from None", source)
        self.assertNotIn("connect_over_cdp", source)
        self.assertLess(source.index("$env:NO_PROXY"), source.index("$currentStage = 'public-dom-gate'"))

    def test_public_dom_gate_checks_idle_controls(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        styles = (SCRIPT.parents[1] / "app/static/styles.css").read_text(encoding="utf-8")

        self.assertIn("['status-label', 'start-btn', 'idle-target-select']", source)
        self.assertIn("body.dataset.state", source)
        self.assertIn("value.get('idleState')", source)
        self.assertIn('body:not([data-state="listening"]):not([data-state="reconnecting"]) #gear-btn', styles)
        self.assertNotIn("['status-label', 'start-btn', 'gear-btn']", source)

        gate = embedded_dom_gate_source()
        marker = "expression = r" + chr(39) * 3
        expression_start = gate.index(marker) + len(marker)
        expression_end = gate.index(chr(39) * 3, expression_start)
        expression = gate[expression_start:expression_end]
        fixture = """
const ids = new Set(['status-label', 'start-btn', 'idle-target-select', 'gear-btn']);
globalThis.document = {
  body: {dataset: {state: 'idle_blocked'}},
  readyState: 'complete',
  getElementById(id) {
    if (!ids.has(id)) return null;
    return {
      id,
      textContent: id === 'status-label' ? 'Checking' : '',
      getBoundingClientRect() { return {width: 100, height: 20}; },
    };
  },
};
globalThis.location = {protocol: 'http:', hostname: '127.0.0.1'};
globalThis.getComputedStyle = (element) => ({
  display: element.id === 'gear-btn' ? 'none' : 'block',
  visibility: 'visible',
});
"""
        result = subprocess.run(
            ["node", "-e", fixture + "console.log(JSON.stringify(eval(" + json.dumps(expression) + ")));"],
            capture_output=True,
            check=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "visible": True,
                "statusNonempty": True,
                "idleState": True,
                "bodyPresent": True,
                "documentComplete": True,
                "loopbackPage": True,
            },
        )

    def test_raw_cdp_failure_reports_only_bounded_state(self) -> None:
        def fail_connect(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("PRIVATE_PROVIDER_BODY")

        websockets = types.ModuleType("websockets")
        sync = types.ModuleType("websockets.sync")
        client = types.ModuleType("websockets.sync.client")
        client.connect = fail_connect  # type: ignore[attr-defined]
        sync.client = client  # type: ignore[attr-defined]
        websockets.sync = sync  # type: ignore[attr-defined]

        stderr = io.StringIO()
        with (
            mock.patch.dict(
                sys.modules,
                {
                    "websockets": websockets,
                    "websockets.sync": sync,
                    "websockets.sync.client": client,
                },
            ),
            mock.patch.object(
                sys,
                "argv",
                ["dom_gate.py", "http://127.0.0.1:8765/", "ws://127.0.0.1:9229/test"],
            ),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            exec(compile(embedded_dom_gate_source(), "dom_gate.py", "exec"), {})

        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "public_dom_gate": "failed",
                "phase": "connect",
                "target_found": False,
                "session_attached": False,
                "evaluation_seen": False,
                "evaluation_exception": False,
                "body_present": False,
                "document_complete": False,
                "loopback_page": False,
                "visible": False,
                "status_nonempty": False,
                "idle_state": False,
            },
        )
        self.assertNotIn("PRIVATE_PROVIDER_BODY", stderr.getvalue())

    def test_listener_cleanup_handles_zero_results_under_strict_mode(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("@(Get-BoundListeners -Ports @($AppPort, $CdpPort)).Count", source)

    def test_raw_cdp_gate_ignores_events_and_returns_only_aggregate_evidence(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeSocket:
            def __init__(self) -> None:
                self.responses: list[str] = []

            def __enter__(self) -> FakeSocket:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def send(self, raw: str) -> None:
                request = json.loads(raw)
                calls.append(request)
                self.responses.append(json.dumps({"method": "Target.targetInfoChanged"}))
                if request["method"] == "Target.getTargets":
                    result = {
                        "targetInfos": [
                            {
                                "targetId": "page-1",
                                "type": "page",
                                "url": "http://127.0.0.1:8765/",
                            }
                        ]
                    }
                elif request["method"] == "Target.attachToTarget":
                    result = {"sessionId": "session-1"}
                else:
                    result = {
                        "result": {
                            "value": {"visible": True, "statusNonempty": True, "idleState": True}
                        }
                    }
                self.responses.append(json.dumps({"id": request["id"], "result": result}))

            def recv(self, timeout: int) -> str:
                self.assert_timeout(timeout)
                return self.responses.pop(0)

            @staticmethod
            def assert_timeout(timeout: int) -> None:
                if timeout != 10:
                    raise AssertionError("unexpected CDP receive timeout")

        def fake_connect(url: str, **kwargs: object) -> FakeSocket:
            self.assertEqual(url, "ws://127.0.0.1:9229/devtools/browser/test")
            self.assertIsNone(kwargs["proxy"])
            return FakeSocket()

        websockets = types.ModuleType("websockets")
        sync = types.ModuleType("websockets.sync")
        client = types.ModuleType("websockets.sync.client")
        client.connect = fake_connect  # type: ignore[attr-defined]
        sync.client = client  # type: ignore[attr-defined]
        websockets.sync = sync  # type: ignore[attr-defined]

        stdout = io.StringIO()
        with (
            mock.patch.dict(
                sys.modules,
                {
                    "websockets": websockets,
                    "websockets.sync": sync,
                    "websockets.sync.client": client,
                },
            ),
            mock.patch.object(
                sys,
                "argv",
                [
                    "dom_gate.py",
                    "http://127.0.0.1:8765/",
                    "ws://127.0.0.1:9229/devtools/browser/test",
                ],
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exec(compile(embedded_dom_gate_source(), "dom_gate.py", "exec"), {})

        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "cdp_loopback": True,
                "page_present": True,
                "public_controls_present": True,
            },
        )
        self.assertEqual(
            [call["method"] for call in calls],
            ["Target.getTargets", "Target.attachToTarget", "Runtime.evaluate"],
        )
        self.assertEqual(calls[-1]["sessionId"], "session-1")


if __name__ == "__main__":
    unittest.main()
