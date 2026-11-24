"""SOFTWARE FIXTURES ONLY. Synthetic review/proof/image bytes are NOT acceptance.

No native process, permissions, provider, input or output is invoked by this suite.
The mocked positive path checks software policy, not authentic physical evidence.
"""
import concurrent.futures
import io
import json
import os
import plistlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.attended_helper_budget import Custody, admit_helper
from scripts.attended_journal import Journal
from scripts.attended_native_admission import CHECKS, IMAGES, CaptureAdmission, digest, document
from scripts.attended_native_launch import EmergencyStop, _terminal, launch_capture, qualify_noinput

ROOT = Path(__file__).resolve().parents[1]


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / 'ledger'
        Journal.initialize(self.ledger, 'a' * 64)
        self.j = Journal(self.ledger, 'a' * 64)
        self.addCleanup(self.j.close)
        self.c = Custody(self.j)
        images = {}
        for name in IMAGES:
            image = self.root / name
            image.write_bytes(b'SOFTWARE_TEST_FIXTURE_NOT_EXECUTABLE:' + name.encode())
            image.chmod(0o700)
            images[name] = digest(image.read_bytes())
        images_sha = digest(raw(images))
        self.proofs = {check: raw(dict(schema='caption-native-proof-v1', candidate='b' * 40,
                      images_sha256=images_sha, check=check, result='PASS', scope='physical',
                      provider_calls=0)) for check in CHECKS}
        self.review = dict(schema='caption-native-review-v1', candidate='b' * 40,
                           disposition='ACCEPT', images=images,
                           proofs={key: digest(value) for key, value in self.proofs.items()})
        self.review_raw = raw(self.review)
        self.authority = self.authorize()

    def authorize(self):
        return CaptureAdmission(self.root, self.review_raw, digest(self.review_raw), self.proofs)

    def grant(self, **changes):
        expires = time.time_ns() + 20_000_000_000
        runtime = raw(dict(schema='caption-native-runtime-proof-v1', candidate='b' * 40,
                      review_sha256=digest(self.review_raw), programme=self.j.programme,
                      ledger_tail=self.j.tail, parent_pid=os.getpid(), expires_unix_ns=expires,
                      kernel_egress_denied=True))
        grant = dict(schema='caption-native-runtime-grant-v1', candidate='b' * 40,
                     review_sha256=digest(self.review_raw), programme=self.j.programme,
                     ledger_tail=self.j.tail, device_id=123, milliseconds=2000,
                     expires_unix_ns=expires, runtime_sha256=digest(runtime),
                     meeting_ended=True, participant_ready=True, private_quiet=True)
        grant.update(changes)
        return raw(grant), runtime

    def issue(self, **changes):
        grant, runtime = self.grant(**changes)
        return self.authority.issue(grant, digest(grant), runtime, self.c)

    def test_default_and_ui_claims_still_refuse(self):
        for kwargs in ({}, dict(identity=True, kernel=True, readiness=True),
                       dict(admission=True, permit=object(), custody=self.c)):
            with self.assertRaises(RuntimeError):
                admit_helper(**kwargs)
        self.assertIsNone(self.j.active)

    def test_no_self_declared_or_changed_review(self):
        with self.assertRaises(ValueError):
            CaptureAdmission(self.root, self.review_raw, '0' * 64, self.proofs)
        proof = json.loads(self.proofs['single_stream'])
        proof['scope'] = 'noinput'
        self.proofs['single_stream'] = raw(proof)
        self.review['proofs']['single_stream'] = digest(raw(proof))
        self.review_raw = raw(self.review)
        with self.assertRaisesRegex(ValueError, 'physical_review'):
            self.authorize()

    def test_duplicate_document_keys_refused(self):
        malformed = b'{"schema":1,"schema":1}'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            document(malformed, digest(malformed), ('schema',))

    def test_runtime_grant_bindings_and_readiness(self):
        for changes in (dict(candidate='c' * 40), dict(review_sha256='0' * 64),
                        dict(programme='c' * 64), dict(ledger_tail='c' * 64),
                        dict(device_id=0), dict(device_id=True), dict(milliseconds=True),
                        dict(milliseconds=2001), dict(meeting_ended=False),
                        dict(participant_ready=1), dict(private_quiet=False),
                        dict(expires_unix_ns=time.time_ns() - 1)):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.issue(**changes)
        self.assertIsNone(self.j.active)

    def test_runtime_network_proof_must_match_grant(self):
        grant, runtime = self.grant()
        runtime = raw(dict(json.loads(runtime), kernel_egress_denied=False))
        with self.assertRaises(ValueError):
            self.authority.issue(grant, digest(grant), runtime, self.c)

    def test_registered_oneuse_permit_and_grant_replay(self):
        grant, runtime = self.grant()
        permit = self.authority.issue(grant, digest(grant), runtime, self.c)
        result = admit_helper(admission=self.authority, permit=permit, custody=self.c)
        self.assertEqual(result['device_id'], 123)
        self.assertIsNone(self.j.active)  # Consumption itself neither debits nor opens.
        with self.assertRaisesRegex(RuntimeError, 'unregistered'):
            self.authority.consume(permit, self.c)
        with self.assertRaisesRegex(RuntimeError, 'replayed'):
            self.authority.issue(grant, digest(grant), runtime, self.c)

    def test_concurrent_permit_consumption_one_winner(self):
        permit = self.issue()
        def take(_):
            try:
                return self.authority.consume(permit, self.c)
            except RuntimeError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(take, range(8)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_replaced_and_symlink_images_refused(self):
        permit = self.issue()
        (self.root / 'CaptureHelper').write_bytes(b'changed SOFTWARE fixture')
        with self.assertRaisesRegex(RuntimeError, 'image_changed'):
            self.authority.consume(permit, self.c)
        image = self.root / 'CaptureHelper'
        image.unlink()
        image.symlink_to(self.root / 'GuardianA')
        with self.assertRaises(OSError):
            self.authorize()

    def test_ledger_change_expiry_and_fork_refused(self):
        permit = self.issue()
        self.j.reserve(1, 'b' * 40, 'c' * 64)
        with self.assertRaisesRegex(RuntimeError, 'ledger_changed'):
            self.authority.consume(permit, self.c)
        self.j.finish('exit')  # Mock ledger only; no input has been started.
        permit = self.issue()
        with patch('scripts.attended_native_admission.time.time_ns', return_value=2**63):
            with self.assertRaisesRegex(RuntimeError, 'expired'):
                self.authority.consume(permit, self.c)
        with patch('scripts.attended_native_admission.os.getpid', return_value=-1):
            with self.assertRaisesRegex(RuntimeError, 'wrong_process'):
                self.authority._verify_images()

    def test_nonmac_never_spawns_or_consumes(self):
        permit = self.issue()
        emergency = EmergencyStop()
        self.addCleanup(emergency.close)
        with patch('scripts.attended_native_launch.sys.platform', 'linux'), \
             patch('scripts.attended_native_launch.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'macos_native_only'):
                launch_capture(self.authority, permit, self.c, emergency)
            with self.assertRaisesRegex(RuntimeError, 'macos_native_only'):
                qualify_noinput(self.root, self.c, 'b' * 40)
            spawn.assert_not_called()
        self.authority.consume(permit, self.c)

    def test_fully_mocked_noinput_debits_before_reply_and_holds(self):
        self.mock_launch(no_input=True)

    def test_fully_mocked_physical_policy_not_physical_evidence(self):
        self.mock_launch(no_input=False)

    def mock_launch(self, *, no_input):
        j = self.j
        class BudgetWriter(io.BytesIO):
            def write(self, wire):
                if j.active is None:
                    raise AssertionError('input wire before fsynced debit')
                expected = b'CBNC0001' if no_input else b'CBCA0001'
                if len(wire) != 56 or not wire.startswith(expected):
                    raise AssertionError('wrong protocol')
                return super().write(wire)
        class FakeChild:
            def __init__(self, arguments, **kwargs):
                if kwargs['env'] or not kwargs['close_fds'] or len(kwargs['pass_fds']) != 1:
                    raise AssertionError('descriptor/environment leak')
                mode = '--capture-noinput-budget' if no_input else '--capture-budget'
                if arguments[1] != mode:
                    raise AssertionError('wrong mode')
                event = 'capture_noinput_budget_ready' if no_input else 'capture_budget_ready'
                lines = [dict(event=event, challenge='d' * 64, ceiling_ms=2000),
                         dict(event='started', pids=[10, 11, 12]),
                         dict(schema=1, capture_exit=0, capture=not no_input, terminal='HOLD',
                              pids=[10, 11, 12], wait_status=[72 << 8] * 3, cleanup_killed=[0]*3)]
                r, w = os.pipe()
                os.write(w, b''.join(raw(line) + b'\n' for line in lines))
                os.close(w)
                self.stdout = os.fdopen(r, 'rb', buffering=0)
                self.stdin = BudgetWriter()
            def wait(self, **kwargs):
                return 0
            def poll(self):
                return 0
        with patch('scripts.attended_native_launch.sys.platform', 'darwin'), \
             patch('scripts.attended_native_launch.subprocess.Popen', FakeChild):
            if no_input:
                result = qualify_noinput(self.root, self.c, 'b' * 40)
            else:
                permit = self.issue()
                emergency = EmergencyStop()
                try:
                    result = launch_capture(self.authority, permit, self.c, emergency)
                finally:
                    emergency.close()
        self.assertFalse(result['physical_acceptance'])
        self.assertFalse(result['native_admission'])
        self.assertIsNotNone(self.j.active)
        self.assertEqual(self.j.charged, 2000)
        with self.assertRaises(RuntimeError):
            Custody(self.j)  # No successful receipt or restart releases HOLD.

    def test_spawn_failure_burns_grant_and_never_opens_or_debits(self):
        permit = self.issue()
        emergency = EmergencyStop()
        self.addCleanup(emergency.close)
        with patch('scripts.attended_native_launch.sys.platform', 'darwin'), \
             patch('scripts.attended_native_launch.subprocess.Popen', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                launch_capture(self.authority, permit, self.c, emergency)
        self.assertIsNone(self.j.active)
        with self.assertRaisesRegex(RuntimeError, 'unregistered'):
            self.authority.consume(permit, self.c)

    def test_native_terminal_must_not_conflate_kill_or_noinput_with_closure(self):
        started = dict(event='started', pids=[10, 11, 12])
        terminal = dict(schema=1, capture_exit=0, capture=False, terminal='HOLD',
                        pids=[10, 11, 12], wait_status=[72 << 8]*3, cleanup_killed=[0]*3)
        for changes in (dict(capture=True), dict(terminal='CLOSED'),
                        dict(cleanup_killed=[0, 0, 1]), dict(wait_status=[72 << 8, 72 << 8, 9]),
                        dict(pids=[10, 11, 13]), dict(capture_exit=True),
                        dict(wait_status=[72 << 8, 72 << 8, 70 << 8])):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                _terminal(started, dict(terminal, **changes), 0, no_input=True)
        self.assertIsNone(self.j.active)

    def test_cross_protocol_reply_cannot_debit(self):
        cap, channel, peer = self.c.session('b' * 40)
        try:
            receipt = self.c.offer(cap, channel, 2000)
            challenge = dict(event='noaudio_budget_ready', challenge='d' * 64, ceiling_ms=2000)
            with self.assertRaises(ValueError):
                self.c.prepare_capture_budget(cap, channel, receipt, challenge, no_input=True)
            self.assertEqual(self.j.charged, 0)
        finally:
            peer.close()
            self.c.revoke(cap)

    def test_emergency_stop_is_terminal_and_private(self):
        emergency = EmergencyStop()
        self.addCleanup(emergency.close)
        self.assertFalse(os.get_inheritable(emergency.reader))
        emergency.stop()
        emergency.stop()
        self.assertEqual(os.read(emergency.reader, 1), b'')
        with self.assertRaises(RuntimeError):
            emergency.ready()


class CaptureSourceTests(unittest.TestCase):
    def test_noinput_never_calls_opener_or_closer(self):
        source = (ROOT / 'native/caption_helper/capture_role.c').read_text()
        self.assertIn('if(options.flags==CB_CAPTURE_ARMED || options.flags==CB_CAPTURE_PCM){', source)
        self.assertIn('if((options.flags==CB_CAPTURE_ARMED || options.flags==CB_CAPTURE_PCM) && cb_capture_close', source)
        self.assertIn('options.flags>CB_CAPTURE_PCM', source)
        self.assertIn('cap.parent!=getppid()', source)
        self.assertIn('cap.deadline-margin', source)

    def test_real_explicit_opener_has_no_output_or_default_device(self):
        source = (ROOT / 'native/caption_helper/capture_input.c').read_text()
        for forbidden in ('kAudioHardwarePropertyDefault', 'AudioQueue', 'fopen(',
                          'socket(', 'system(', 'execve(', 'dlopen('):
            self.assertNotIn(forbidden, source)
        self.assertLess(source.index('kAudioOutputUnitProperty_CurrentDevice'),
                        source.index('AudioUnitInitialize('))
        self.assertIn('kAudioUnitScope_Output,0,&no', source)
        self.assertIn('AudioUnitRender(', source)
        self.assertIn('AudioOutputUnitStop(', source)
        self.assertIn('AudioComponentInstanceDispose(', source)

    def test_native_format_and_emergency_are_bounded_not_asr_assumptions(self):
        source = (ROOT / 'native/caption_helper/capture_input.c').read_text()
        for invariant in ('AudioUnitGetProperty(', 'format.mSampleRate>192000',
                          'format.mChannelsPerFrame>32', 'CB_MAX_FRAMES', '>1048576',
                          'kAudioFormatFlagIsNonInterleaved', '.fd=9', 'poll(p,4,0)'):
            self.assertIn(invariant, source)
        self.assertNotIn('format.mSampleRate=16000', source)
        role = (ROOT / 'native/caption_helper/capture_role.c').read_text()
        self.assertIn('if(!reader_pipe(9))return 66', role)
        controller = (ROOT / 'native/caption_helper/assembly.c').read_text()
        self.assertIn('posix_spawn_file_actions_adddup2(&f,stop_copy,9)', controller)
        self.assertIn('poll(&before_spawn,1,0)!=0', controller)

    def test_capture_entitlement_allowlist(self):
        entitlements = plistlib.loads((ROOT / 'native/caption_helper/capture_entitlements.plist').read_bytes())
        self.assertEqual(entitlements, {'com.apple.security.app-sandbox': True,
                                       'com.apple.security.device.microphone': True})
        self.assertNotIn('network', str(entitlements))

    def test_existing_qualification_entrypoint_stays_noaudio(self):
        builder = (ROOT / 'scripts/build_caption_helper.sh').read_text()
        self.assertNotIn('capture_input', builder)
        self.assertNotIn('CaptureController', builder)
        source = (ROOT / 'native/caption_helper/main.c').read_text()
        self.assertIn('return 64; /* Includes --capture', source)


if __name__ == '__main__':
    unittest.main()
