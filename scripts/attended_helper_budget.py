"""Parent-owned allowance protocol, NEVER native admission.

One coordinator holds one locked Journal for ALL devices, failures and retries.
Ephemeral capabilities/key remain in parent memory, never JSON/argv/files. Parent
creates inherited socketpair endpoints; reconnects and claimed PIDs are not proof.
Receipts prove custody only, not helper identity, kernel safety or human readiness.
Native verification/launch remains unavailable. Crash loses key and retains hold.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass

from scripts.attended_acceptance import CAP_MS, hex_id
from scripts.attended_journal import encoded


@dataclass(frozen=True)
class Receipt:
    payload: bytes
    mac: str

@dataclass(frozen=True)
class LaunchReservation:
    """Parent-local ceiling, never identity, readiness or capture authority.

    Starts before durable debit. A qualified native launcher must convert remaining
    duration to mach_continuous_time, Python monotonic is not suspend-safe proof.
    """
    sequence: int
    candidate: str
    reserved_ms: int
    deadline_ns: int
    native_admission: bool = False


class Custody:
    """Parent-only authority. Keep its Journal exclusively locked for its lifetime.

    Thread lock serializes receipt consumption and durable debit. Journal flock
    excludes other processes. Unknown closure is never released here. Socket
    identity binds only transport custody, NOT the identity of its remote peer.
    """
    def __init__(self, journal):
        if journal.active is not None or journal.poisoned:
            raise RuntimeError('custody_unclosed')
        self._journal = journal
        self._key = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._sessions = {}
        self._launches = {}
        self._issued = {}
        self._pid = os.getpid()

    def _parent(self):
        if os.getpid() != self._pid:
            raise RuntimeError('custody_wrong_process')

    def session(self, candidate):
        """Return local opaque capability, parent endpoint, future helper endpoint."""
        self._parent()
        if not hex_id(candidate, 40):
            raise ValueError('candidate')
        parent, helper = socket.socketpair()
        capability = object()
        with self._lock:
            self._sessions[capability] = (candidate, parent, os.fstat(parent.fileno()))
        return capability, parent, helper

    def _binding(self, capability, channel):
        self._parent()
        entry = self._sessions.get(capability)
        if entry is None or channel is not entry[1]:
            raise RuntimeError('session_binding')
        st = os.fstat(channel.fileno())
        old = entry[2]
        if (st.st_dev, st.st_ino) != (old.st_dev, old.st_ino):
            raise RuntimeError('channel_replaced')
        return entry[0]

    def offer(self, capability, channel, ms, *, ttl_ms=1000):
        """Parent approval token only. No readiness claim or capture side effect."""
        with self._lock:
            candidate = self._binding(capability, channel)
            now = time.monotonic_ns()
            self._issued = {k: v for k, v in self._issued.items() if v[5] > now}
            if len(self._issued) >= 64:
                raise RuntimeError('pending_offer_limit')
            if (type(ms) is not int or not 0 < ms <= CAP_MS
                    or type(ttl_ms) is not int or not 0 < ttl_ms <= 1000):
                raise ValueError('offer_duration')
            expires = time.monotonic_ns() + ttl_ms * 1_000_000
            payload = encoded({'programme': self._journal.programme,
                               'candidate': candidate, 'ms': ms,
                               'tail': self._journal.tail, 'expires_ns': expires,
                               'nonce': secrets.token_hex(32)})
            receipt = Receipt(payload, hmac.new(self._key, b'allowance-v1' + payload,
                                               hashlib.sha256).hexdigest())
            self._issued[receipt.mac] = (capability, channel, receipt, ms,
                                        self._journal.tail, expires)
            return receipt

    def reserve(self, capability, channel, receipt):
        """Consume once and fsync full debit before any future launch."""
        with self._lock:
            candidate = self._binding(capability, channel)
            if not isinstance(receipt, Receipt):
                raise RuntimeError('receipt_invalid')
            expected = hmac.new(self._key, b'allowance-v1' + receipt.payload,
                                hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, receipt.mac):
                raise RuntimeError('receipt_authentication')
            entry = self._issued.pop(receipt.mac, None)
            if (entry is None or entry[0] is not capability or entry[1] is not channel
                    or entry[2] != receipt or entry[4] != self._journal.tail
                    or time.monotonic_ns() >= entry[5]):
                raise RuntimeError('receipt_stale_or_replayed')
            self._journal.reserve(entry[3], candidate,
                                  hashlib.sha256(receipt.payload).hexdigest())
            return self._journal.active['sequence']

    def prepare_launch(self, capability, channel, receipt):
        """Debit before launch preparation. No launch, input, refund or admission.

        Journal serializes all devices. Expiry after debit retains the hold.
        The native identity/readiness/closure verifier remains unavailable.
        """
        started = time.monotonic_ns()
        sequence = self.reserve(capability, channel, receipt)
        with self._lock:
            active = self._journal.active
            reservation = LaunchReservation(sequence, active['candidate'], active['ms'],
                                            started + active['ms'] * 1_000_000)
            self._launches[capability] = reservation
        self.launch_remaining_ns(capability, channel, reservation)
        return reservation

    def prepare_noaudio_budget(self, capability, channel, receipt, challenge_event):
        """Reply only after durable debit to an already-started noaudio handshake.

        Caller must own the controller, inherited FD0 writer and bounded stdout
        reader. This method does not spawn, send, authenticate native identity or
        close a reservation. Native's anchor precedes its challenge, and therefore
        precedes this debit: using the FULL reserved duration is conservative even
        across scheduling, fsync and system sleep. Python clocks are not translated
        to native ticks. Native independently rejects late/trailing/wrong replies.
        A fake challenge can waste budget, never confer capture authority.
        """
        if (type(challenge_event) is not dict
                or set(challenge_event) != {'event', 'challenge', 'ceiling_ms'}
                or challenge_event['event'] != 'noaudio_budget_ready'
                or type(challenge_event['ceiling_ms']) is not int
                or challenge_event['ceiling_ms'] != 2000
                or not hex_id(challenge_event['challenge'], 64)):
            raise ValueError('noaudio_budget_challenge')
        reservation = self.prepare_launch(capability, channel, receipt)
        if reservation.reserved_ms > 2000 or reservation.sequence >= 2**64:
            # An unsupported envelope was already debited, never refund it.
            with self._lock:
                self._launches.pop(capability, None)
            raise RuntimeError('noaudio_budget_limit_hold')
        wire = (b'CBNA0001' + bytes.fromhex(challenge_event['challenge'])
                + (reservation.reserved_ms * 1_000_000).to_bytes(8, 'big')
                + reservation.sequence.to_bytes(8, 'big'))
        return reservation, wire

    def launch_remaining_ns(self, capability, channel, reservation):
        """Validate live parent custody and debit, never grant native admission."""
        with self._lock:
            candidate = self._binding(capability, channel)
            active = self._journal.active
            if (type(reservation) is not LaunchReservation
                    or self._launches.get(capability) is not reservation
                    or active is None or self._journal.poisoned
                    or self._journal.fd is None
                    or active['sequence'] != reservation.sequence
                    or active['candidate'] != candidate):
                raise RuntimeError('launch_binding')
            now = time.monotonic_ns()
            if now < reservation.deadline_ns - reservation.reserved_ms * 1_000_000:
                self._launches.pop(capability, None)
                raise RuntimeError('launch_clock_regressed_hold')
            remaining = reservation.deadline_ns - now
            if remaining <= 0:
                self._launches.pop(capability, None)
                raise RuntimeError('launch_allowance_expired_hold')
            return remaining

    def revoke(self, capability):
        """Close owned parent endpoint only; never clear an outstanding hold."""
        self._parent()
        with self._lock:
            entry = self._sessions.pop(capability, None)
            self._launches.pop(capability, None)
            self._issued = {k: v for k, v in self._issued.items() if v[0] is not capability}
            if entry is not None:
                entry[1].close()


def admit_helper(*_args, **_kwargs):
    """Future adapter injection boundary, deliberately no callable verifier yet.

    Require OS peer/code identity on inherited IPC, fresh session/challenge-bound
    helper+guardian proofs, kernel deny, single-input/deadline/cleanup verification
    and explicit human readiness. MACs/hashes/booleans do not substitute for these.
    Reserve before input; independently verify terminal state before journal close.
    Unknown terminal state retains permanent debit AND admission hold. Route change
    must mute first. No auto admission, provider access, output or native launch.
    """
    raise RuntimeError('helper_identity_kernel_readiness_verifier_unavailable')
