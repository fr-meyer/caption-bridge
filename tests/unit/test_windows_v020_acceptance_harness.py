from __future__ import annotations

import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "windows_v020_acceptance.ps1"


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

    def test_listener_cleanup_handles_zero_results_under_strict_mode(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("@(Get-BoundListeners -Ports @($AppPort, $CdpPort)).Count", source)


if __name__ == "__main__":
    unittest.main()
