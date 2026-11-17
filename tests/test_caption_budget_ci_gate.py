"""Execute the exact workflow budget gate with offline receipt/image fixtures only."""
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from native.caption_helper import newqualifysuite as suite

ROOT = Path(__file__).resolve().parents[1]


def workflow_ast():
    text = (ROOT / '.github/workflows/ci.yml').read_text()
    marker = "          uv run --no-sync --python 3.13 python - <<'PYTHON'\n"
    body = text.split(marker, 1)[1].split('          PYTHON', 1)[0]
    return ast.parse('\n'.join(line[10:] if line.startswith('          ') else line
                               for line in body.splitlines()))


def stage(node, value):
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'stage'
            and isinstance(node.value, ast.Constant) and node.value.value == value)


def fixture(passed=True):
    rows = [suite.row(name, True, 'COMPLETE', 2000) for name in suite.SCENARIOS]
    if not passed:
        rows[0] = suite.row(suite.SCENARIOS[0], False, 'TERMINAL', 2000)
    return json.dumps(suite.receipt(rows)).encode()


class BudgetCIGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.images = Path(self.tmp.name)
        hashes = {}
        for name in ('GuardianA', 'GuardianB', 'SyntheticHelper', 'NoAudioController'):
            data = ('offline-image-fixture-' + name).encode()
            (self.images / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        self.receipt = dict(image_hashes=hashes, probe_outcome='NOT_RUN')
        tree = workflow_ast()
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'checked_budget_harness')
        main = next(n for n in tree.body if isinstance(n, ast.Try))
        start = next(i for i, n in enumerate(main.body) if stage(n, 'budget_identity'))
        self.gate = compile(ast.Module(body=[helper, *main.body[start:]], type_ignores=[]),
                            '<exact-workflow-budget-gate>', 'exec')
        self.calls = []

    def run_gate(self, raw=None, code=0, after=None):
        raw = fixture() if raw is None else raw

        def bounded(args, timeout, *, check=True):
            self.calls.append((args, timeout, check))
            self.receipt['returncode'] = code
            if after is not None:
                after()
            return raw

        namespace = dict(hashlib=hashlib, images=self.images, receipt=self.receipt,
                         sys=sys, bounded=bounded)
        exec(self.gate, namespace)

    def test_exact_success_and_fixed_module_argv(self):
        self.run_gate()
        self.assertEqual(self.receipt['probe_outcome'], 'PASS')
        self.assertEqual(self.receipt['budget_harness'], json.loads(fixture()))
        self.assertEqual(self.calls, [([sys.executable, '-m',
                         'native.caption_helper.newqualifysuite', str(self.images)], 95, False)])
        self.assertIs(self.receipt['budget_harness']['capture'], False)
        self.assertEqual(self.receipt['budget_harness']['terminal'], 'HOLD')

    def test_native_suite_failure_retained_but_never_promoted(self):
        with self.assertRaisesRegex(ValueError, 'budget_qualification_failed'):
            self.run_gate(fixture(False), 1)
        self.assertEqual(self.receipt['budget_harness']['result'], 'FAIL')
        self.assertEqual(self.receipt['probe_outcome'], 'NOT_RUN')
        self.assertEqual(self.receipt['error_class'], 'QualificationFailed')

    def test_exit_and_receipt_success_must_agree(self):
        for raw, code in ((fixture(False), 0), (fixture(), 1), (fixture(), -9)):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, 'exit_mismatch'):
                self.run_gate(raw, code)
            self.assertNotIn('budget_harness', self.receipt)
            self.assertNotEqual(self.receipt['probe_outcome'], 'PASS')

    def test_foreign_malformed_duplicate_oversize_never_projected(self):
        value = json.loads(fixture())
        value['secret'] = 'PRIVATE_DATA'
        bad = [json.dumps(value).encode(), b'PRIVATE_DATA', b'x' * 4097,
               fixture().replace(b'"schema": 1', b'"schema": 1,"schema": 1'),
               b'[' * 1000]
        for raw in bad:
            with self.subTest(size=len(raw)), self.assertRaisesRegex(ValueError, 'receipt_schema'):
                self.run_gate(raw)
            self.assertNotIn('budget_harness', self.receipt)
            self.assertNotIn('PRIVATE_DATA', json.dumps(self.receipt))

    def test_incomplete_scenarios_never_accepted(self):
        value = json.loads(fixture())
        value['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'receipt_schema'):
            self.run_gate(json.dumps(value).encode())

    def test_image_drift_before_prevents_any_execution(self):
        (self.images / 'NoAudioController').write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError, 'budget_image_drift'):
            self.run_gate()
        self.assertEqual(self.calls, [])

    def test_image_drift_after_prevents_qualification(self):
        with self.assertRaisesRegex(ValueError, 'budget_image_drift'):
            self.run_gate(after=lambda: (self.images / 'SyntheticHelper').write_bytes(b'drift'))
        self.assertNotEqual(self.receipt['probe_outcome'], 'PASS')

    def test_old_matrix_precedes_new_gate_and_outer_privacy_hold_remain(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertLess(text.index('native/caption_helper/qualify_assembly.py'),
                        text.index('stage = "budget_identity"'))
        self.assertIn('receipt["harness"] = checked_harness(raw)', text)
        self.assertIn('"terminal": "HOLD"', text)
        self.assertIn('"capture_authorized": False', text)
        self.assertIn('receipt["probe_outcome"] = "FAIL"', text)
        self.assertIn('receipt_path.write_text', text)
        self.assertIn('timeout-minutes: 4', text)
        compile(workflow_ast(), '<exact-complete-workflow-python>', 'exec')


if __name__ == '__main__':
    unittest.main()
