"""Explicit, pinned review + one-use attended grant. No device/process side effects.

Trust boundary: expected review/grant digests come from the coordinator's reviewed
release/owner channel, NEVER from the document being checked or UI booleans. This
is not an attestation service. The coordinator must authenticate those external
observations. No default trust pins, grants, credential route or auto-enable exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from pathlib import Path

from scripts.attended_acceptance import hex_id
from scripts.attended_native_clock import continuous_ns

MIN_CAPTURE_MS = 1000
IMAGES = ('CaptureController', 'CaptureGuardianA', 'CaptureGuardianB', 'CaptureHelper')
CHECKS = ('signature_entitlements', 'kernel_egress_denied', 'single_stream',
          'deadline_close', 'controller_death_close', 'guardian_death_close',
          'suspend_close', 'emergency_stop', 'mute_before_route_change', 'native_cleanup')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def document(raw, expected, keys):
    if (type(raw) is not bytes or len(raw) > 65536 or not hex_id(expected, 64)
            or digest(raw) != expected):
        raise ValueError('trusted_document_pin')
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('document_schema')
    return value


def _image_digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & 0o022 or not before.st_mode & 0o111
                or before.st_size > 32 * 1024 * 1024):
            raise ValueError('image_permissions')
        result = hashlib.sha256()
        consumed = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > 32 * 1024 * 1024:
                raise RuntimeError('image_size_changed')
            result.update(chunk)
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
             before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
                                    after.st_mtime_ns, after.st_ctime_ns)):
            raise RuntimeError('image_changed')
        return result.hexdigest()
    finally:
        os.close(fd)


class CaptureAdmission:
    """Parent-memory review authority, not a serialized admission boolean.

    A copied/forged permit is not registered. Consumption is process/thread bound,
    burns the permit BEFORE launch, and never finishes or refunds the Journal.
    Receipt hashes authenticate bytes only via the caller's independent trust pins.
    Native suspended spawn additionally enforces built-in exact disk/live CDHashes.
    Same-user root-directory replacement/exec races need platform qualification,
    not a claim that Python hashing creates an OS identity lock.
    """
    def __init__(self, root, review_raw, trusted_review_sha256, proofs):
        review = document(review_raw, trusted_review_sha256,
                          ('schema', 'candidate', 'disposition', 'images', 'proofs'))
        if (review['schema'] != 'caption-native-review-v1'
                or not hex_id(review['candidate'], 40) or review['disposition'] != 'ACCEPT'
                or type(review['images']) is not dict or set(review['images']) != set(IMAGES)
                or any(not hex_id(value, 64) for value in review['images'].values())
                or type(review['proofs']) is not dict or set(review['proofs']) != set(CHECKS)
                or type(proofs) is not dict or set(proofs) != set(CHECKS)):
            raise ValueError('review_binding')
        image_set = digest(json.dumps(review['images'], sort_keys=True,
                                      separators=(',', ':')).encode())
        for check in CHECKS:
            proof = document(proofs[check], review['proofs'][check],
                             ('schema', 'candidate', 'images_sha256', 'check', 'result',
                              'scope', 'provider_calls'))
            if proof != dict(schema='caption-native-proof-v1', candidate=review['candidate'],
                             images_sha256=image_set, check=check, result='PASS',
                             scope='physical', provider_calls=0) or type(proof['provider_calls']) is not int:
                raise ValueError('physical_review_evidence_required')
        self.root = Path(root).resolve(strict=True)
        self.candidate = review['candidate']
        self.review_sha256 = trusted_review_sha256
        self._images = dict(review['images'])
        self._pid = os.getpid()
        self._permits = {}
        self._seen_grants = set()
        self._lock = threading.Lock()
        self._verify_images()

    def _verify_images(self):
        if os.getpid() != self._pid:
            raise RuntimeError('admission_wrong_process')
        for name, expected in self._images.items():
            if _image_digest(self.root / name) != expected:
                raise RuntimeError('reviewed_image_changed')

    def issue(self, grant_raw, trusted_grant_sha256, runtime_proof_raw, custody):
        """Register exactly one externally authenticated, short-lived runtime grant.

        No owner grant or real runtime proof is manufactured by this module.
        Historical/noinput/fixture receipts cannot satisfy the physical review schema.
        """
        grant = document(grant_raw, trusted_grant_sha256,
                         ('schema', 'candidate', 'review_sha256', 'programme', 'ledger_tail',
                          'device_id', 'milliseconds', 'expires_unix_ns', 'runtime_sha256',
                          'meeting_ended', 'participant_ready', 'private_quiet'))
        runtime = document(runtime_proof_raw, grant['runtime_sha256'],
                           ('schema', 'candidate', 'review_sha256', 'programme', 'ledger_tail',
                            'parent_pid', 'expires_unix_ns', 'kernel_egress_denied'))
        journal = custody._journal
        clock_anchor = continuous_ns()
        now = grant_wall_now = time.time_ns()
        if (grant['schema'] != 'caption-native-runtime-grant-v1'
                or grant['candidate'] != self.candidate
                or grant['review_sha256'] != self.review_sha256
                or grant['programme'] != journal.programme or grant['ledger_tail'] != journal.tail
                or journal.active is not None or journal.poisoned or journal.fd is None
                or type(grant['device_id']) is not int or not 1 <= grant['device_id'] < 2**32
                or type(grant['milliseconds']) is not int or not MIN_CAPTURE_MS <= grant['milliseconds'] <= 2000
                or type(grant['expires_unix_ns']) is not int
                or not now < grant['expires_unix_ns'] <= now + 60_000_000_000
                or any(grant[key] is not True for key in ('meeting_ended', 'participant_ready', 'private_quiet'))
                or runtime != dict(schema='caption-native-runtime-proof-v1', candidate=self.candidate,
                                   review_sha256=self.review_sha256, programme=journal.programme,
                                   ledger_tail=journal.tail, parent_pid=self._pid,
                                   expires_unix_ns=grant['expires_unix_ns'], kernel_egress_denied=True)
                or runtime['kernel_egress_denied'] is not True
                or type(runtime['parent_pid']) is not int
                or type(runtime['expires_unix_ns']) is not int):
            raise RuntimeError('runtime_grant_binding')
        self._verify_images()
        permit = object()
        with self._lock:
            self._permits = {p: v for p, v in self._permits.items() if now < v[0]['expires_unix_ns'] and continuous_ns() < v[5]}
            if self._permits or trusted_grant_sha256 in self._seen_grants:
                raise RuntimeError('runtime_grant_pending_or_replayed')
            self._seen_grants.add(trusted_grant_sha256)
            self._permits[permit] = (grant, custody, journal.tail, now, trusted_grant_sha256, clock_anchor + grant['expires_unix_ns'] - grant_wall_now)
        return permit

    def consume(self, permit, custody):
        with self._lock:
            entry = self._permits.pop(permit, None)
            if entry is None or entry[1] is not custody:
                raise RuntimeError('runtime_grant_unregistered')
            grant, _, tail, issued, grant_sha256, valid_until_continuous_ns = entry
            journal = custody._journal
            now = time.time_ns()
            if (continuous_ns() >= valid_until_continuous_ns
                    or not issued <= now < grant['expires_unix_ns'] or journal.tail != tail
                    or journal.active is not None or journal.poisoned or journal.fd is None):
                raise RuntimeError('runtime_grant_expired_or_ledger_changed')
            self._verify_images()
            return dict(candidate=self.candidate, root=self.root,
                        milliseconds=grant['milliseconds'], device_id=grant['device_id'],
                        expires_unix_ns=grant['expires_unix_ns'], ledger_tail=tail, grant_sha256=grant_sha256, valid_until_continuous_ns=valid_until_continuous_ns)
