"""Dependency-free contract checks against the real diagnostic source.

AST extraction excludes imports only, so bare CI/bootstrap hosts can run these
without SDK, device, credential, provider or application initialization.
"""
import ast
import json
import logging
import types
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


def load_diagnostics():
    source = ast.parse(Path("app/asr_diagnostics.py").read_text())
    pipeline = ast.parse(Path("app/pipeline_diagnostics.py").read_text())
    env = {"__name__": "asr_contract", "json": json, "logging": logging, "uuid": uuid,
           "datetime": datetime, "timezone": timezone}
    assignments = [node for node in pipeline.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id in {"ASR_REASONS_V5", "ASR_REASONS"}
                           for t in node.targets)]
    nodes = assignments + [node for node in source.body
                           if isinstance(node, (ast.Assign, ast.FunctionDef, ast.ClassDef))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "asr_diagnostics", "exec"), env)
    return env["AsrDiagnostics"]


class RecoveryContractTests(unittest.TestCase):
    def test_retry_lifecycle_is_correlated_and_safe(self):
        diagnostic = load_diagnostics()()
        error = RuntimeError("PRIVATE caption audio provider body device-id")
        error.reason = "PRIVATE reason"
        info = types.SimpleNamespace(category="PRIVATE category", status_code=True,
                                     close_code=999999)
        records = []
        with patch.object(logging.getLogger("builtins"), "log"):
            # The extracted source uses this test module's logger name.
            with patch.object(logging.Logger, "log", lambda self, level, fmt, row: records.append(json.loads(row))):
                self.assertTrue(diagnostic.failure(error, attempt_id=1, info=info))
                self.assertFalse(diagnostic.failure(error, attempt_id=1, info=info))
                for event in ("reconnect_started", "reconnect_attempt", "reconnect_attempt_failed",
                              "recovered", "exhausted", "cancelled"):
                    diagnostic.emit(event, attempt_id=2, downtime_ms=42)
        self.assertEqual(len(records), 7)
        self.assertEqual(len({r["run_id"] for r in records}), 1)
        self.assertNotIn("PRIVATE", json.dumps(records))
        self.assertIsNone(records[0]["status_code"])
        self.assertIsNone(records[0]["close_code"])
        self.assertEqual(records[-1]["downtime_ms"], 42)
        self.assertIsNotNone(datetime.fromisoformat(records[0]["at_utc"]).tzinfo)

    def test_new_run_and_invalid_event(self):
        diagnostic = load_diagnostics()()
        old = diagnostic.run_id
        diagnostic.new_run()
        self.assertNotEqual(old, diagnostic.run_id)
        with self.assertRaises(ValueError):
            diagnostic.emit("PRIVATE", attempt_id=0)
        with self.assertRaises(ValueError):
            diagnostic.emit("stream_failure", attempt_id=True)


if __name__ == "__main__":
    unittest.main()
