"""Additional PCM egress authority. Discard-only permits never authorize PCM.

Trusted digests MUST arrive through the independent reviewed owner channel. No
source-provided pin, UI flag, fixture, ledger reset or automatic grant exists.
"""
from __future__ import annotations

import os
import threading
import time

from scripts.attended_acceptance import hex_id
from scripts.attended_native_clock import continuous_ns
from scripts.attended_native_admission import CaptureAdmission, document

PCM_CHECKS = ("framing_epoch", "bounded_backpressure_close", "stop_drain",
              "no_retention", "consumer_boundary")


class PcmAdmission:
    def __init__(self, base, review_raw, trusted_review_sha256, proofs):
        if type(base) is not CaptureAdmission:
            raise RuntimeError("native_pcm_base_admission_required")
        review = document(review_raw, trusted_review_sha256,
                          ("schema", "candidate", "base_review_sha256", "consumer", "provider_authority_sha256", "proofs"))
        if (review["schema"] != "caption-native-pcm-review-v1"
                or review["candidate"] != base.candidate
                or review["base_review_sha256"] != base.review_sha256
                or review["consumer"] not in ("offline", "app-asr")
                or (review["consumer"] == "app-asr" and not hex_id(review["provider_authority_sha256"], 64))
                or (review["consumer"] == "offline" and review["provider_authority_sha256"] is not None)
                or type(review["proofs"]) is not dict or set(review["proofs"]) != set(PCM_CHECKS)
                or type(proofs) is not dict or set(proofs) != set(PCM_CHECKS)):
            raise RuntimeError("native_pcm_review_binding")
        for check in PCM_CHECKS:
            proof = document(proofs[check], review["proofs"][check],
                             ("schema", "candidate", "base_review_sha256", "consumer",
                              "check", "scope", "result", "provider_calls"))
            if (proof != dict(schema="caption-native-pcm-proof-v1", candidate=base.candidate,
                              base_review_sha256=base.review_sha256, consumer=review["consumer"],
                              check=check, scope="physical", result="PASS", provider_calls=0)
                    or type(proof["provider_calls"]) is not int):
                raise RuntimeError("native_pcm_physical_proof_required")
        self.base = base
        self.consumer = review["consumer"]
        self.provider_authority_sha256 = review["provider_authority_sha256"]
        self.review_sha256 = trusted_review_sha256
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._seen = set()
        self._permits = {}

    def issue(self, grant_raw, trusted_grant_sha256, custody, base_permit):
        clock_anchor = continuous_ns()
        wall_now = time.time_ns()
        grant = document(grant_raw, trusted_grant_sha256,
                         ("schema", "candidate", "review_sha256", "base_grant_sha256", "programme", "ledger_tail",
                          "session_id", "generation", "epoch", "asr_sample_rate", "consumer",
                          "expires_unix_ns", "provider_authority_sha256"))
        if (os.getpid() != self._pid
                or grant["schema"] != "caption-native-pcm-grant-v1"
                or grant["candidate"] != self.base.candidate
                or grant["review_sha256"] != self.review_sha256
                or not hex_id(grant["base_grant_sha256"], 64)
                or grant["programme"] != custody._journal.programme
                or grant["ledger_tail"] != custody._journal.tail
                or type(grant["session_id"]) is not str or not 1 <= len(grant["session_id"]) <= 128
                or type(grant["generation"]) is not int or not 1 <= grant["generation"] < 2**63
                or not hex_id(grant["epoch"], 32) or grant["epoch"] == "0" * 32
                or type(grant["asr_sample_rate"]) is not int or grant["asr_sample_rate"] != 16000
                or grant["consumer"] != self.consumer
                or grant["provider_authority_sha256"] != self.provider_authority_sha256
                or type(grant["expires_unix_ns"]) is not int
                or not wall_now < grant["expires_unix_ns"] <= wall_now + 60_000_000_000
                or (self.consumer == "app-asr" and not hex_id(grant["provider_authority_sha256"], 64))
                or (self.consumer == "offline" and grant["provider_authority_sha256"] is not None)):
            raise RuntimeError("native_pcm_grant_binding")
        # provider_authority_sha256 is an externally authenticated authorization
        # reference, not a budget counter or inferred permission to spend. The
        # coordinator must validate it under existing provider admission rules.
        permit = object()
        with self._lock:
            if self._permits or trusted_grant_sha256 in self._seen or grant["epoch"] in self._seen:
                raise RuntimeError("native_pcm_grant_replayed")
            self._seen.update((trusted_grant_sha256, grant["epoch"]))
            self._permits[permit] = (grant, custody, base_permit, clock_anchor + grant["expires_unix_ns"] - wall_now)
        return permit

    def consume(self, permit, custody, *, session_id, generation, sample_rate, consumer):
        with self._lock:
            entry = self._permits.pop(permit, None)
            if entry is None or entry[1] is not custody or os.getpid() != self._pid:
                raise RuntimeError("native_pcm_not_admitted")
            grant, _, base_permit, valid_until_continuous_ns = entry
            if (grant["session_id"] != session_id or grant["generation"] != generation
                    or type(generation) is not int or sample_rate != grant["asr_sample_rate"]
                    or type(sample_rate) is not int or consumer != grant["consumer"]
                    or continuous_ns() >= valid_until_continuous_ns
                    or time.time_ns() >= grant["expires_unix_ns"]):
                raise RuntimeError("native_pcm_session_binding")
            launch = self.base.consume(base_permit, custody)
            if (launch["grant_sha256"] != grant["base_grant_sha256"]
                    or launch["ledger_tail"] != grant["ledger_tail"]
                    or grant["expires_unix_ns"] > launch["expires_unix_ns"]):
                raise RuntimeError("native_pcm_runtime_binding")
            return dict(launch, epoch=grant["epoch"], session_id=session_id, generation=generation,
                        pcm_expires_unix_ns=grant["expires_unix_ns"],
                        valid_until_continuous_ns=min(launch["valid_until_continuous_ns"], valid_until_continuous_ns))
