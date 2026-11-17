"""No subprocess/native calls: diagnostic wrapper fixtures."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "native/caption_helper/qualify_assembly.py"
spec = importlib.util.spec_from_file_location("diagnostic_qualifier", PATH)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class DiagnosticsTests(unittest.TestCase):
    def test_before_startup_privacy(self):
        with patch.object(q, "execute", side_effect=OSError("SECRET_PATH")):
            result, code = q.run("not-used")
        self.assertEqual(code, 1)
        self.assertEqual(result["failure"]["error_class"], "OSError")
        self.assertIsNone(result["failure"]["startup"])
        self.assertNotIn("SECRET_PATH", json.dumps(result))

    def test_early_hold_and_wrong_wait_mode(self):
        terminal = dict(
            schema=5, noaudio_exit=70, terminal="HOLD", pids=[21, -1, -1], wait_status=[-1, -1, -1]
        )

        def failure(root, state):
            state.update(
                mode="guardian_a", stage="wait_status", terminal=q.validate_terminal(terminal)
            )
            raise AssertionError("PRIVATE")

        with patch.object(q, "execute", side_effect=failure):
            result, code = q.run("not-used")
        self.assertEqual(code, 1)
        self.assertEqual(result["failure"]["terminal"], terminal)
        self.assertEqual(result["failure"]["stage"], "wait_status")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_unvalidated_extra_fields_never_projected(self):
        self.assertIsNone(q.validate_startup(dict(event="started", pids=[21, 22, 23], secret="x")))
        self.assertIsNone(
            q.validate_terminal(
                dict(
                    schema=5,
                    noaudio_exit=70,
                    terminal="HOLD",
                    pids=[21, -1, -1],
                    wait_status=[-1] * 3,
                    secret="x",
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
