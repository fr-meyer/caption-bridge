"""Bounded source invariants for native-only code, no native execution."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "native" / "caption_helper"


class ReadinessTests(unittest.TestCase):
    def test_identity_retained_before_verification(self):
        source = (ROOT / "assembly.c").read_text()
        self.assertLess(
            source.index("owned_identity[role-1]=pid"), source.index("if(!verify(pid,path,role))")
        )
        self.assertIn("else retained[role-1]=-1", source)
        self.assertIn("if(retained[i]>0)", source)

    def test_readiness_checks_pid_and_role(self):
        source = (ROOT / "assembly.c").read_text()
        self.assertIn("ready.pid!=pid || ready.role!=(uint32_t)role", source)
        self.assertIn("received<sizeof(ready) && mach_continuous_time()<deadline", source)
        self.assertIn("F_DUPFD_CLOEXEC,30", source)
        self.assertLess(source.index("if(received!=sizeof(ready)"), source.index("ok=1;"))

    def test_early_failure_keeps_identities(self):
        source = (ROOT / "assembly.c").read_text()
        self.assertIn("identities[i]=owned_identity[i]", source)
        role = (ROOT / "role.c").read_text()
        self.assertLess(role.index("ready={getpid(),CAPTION_ROLE}"), role.index("for(;;)"))


if __name__ == "__main__":
    unittest.main()


class AttributionTests(unittest.TestCase):
    def test_deadline_only_fixture_is_not_parent_mechanism_qualification(self):
        # Parent-monitor-disabled role can exit at its deadline and be OS-reaped.
        fixture = {
            "parent_monitor_enabled": False,
            "deadline_exit_seconds": 2,
            "observed_esrch_seconds": 2.1,
        }
        aggregate_closure = fixture["observed_esrch_seconds"] <= 3
        unique_parent_mechanism = fixture["parent_monitor_enabled"]
        self.assertTrue(aggregate_closure)
        self.assertFalse(unique_parent_mechanism)
        harness = (ROOT / "qualify_assembly.py").read_text()
        self.assertIn("ESRCH_AFTER_OS_REAPER_PARENT_OR_DEADLINE", harness)
        self.assertNotIn("PARENT_DEATH_QUALIFIED", harness)
        self.assertIn(
            "cb_capture_admitted(void) { return false; }", (ROOT / "input_state.h").read_text()
        )
