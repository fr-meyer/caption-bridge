"""SOFTWARE MOCKS ONLY: forged fixture proofs are not real physical acceptance."""
import json
from unittest.mock import patch

import pytest
import test_caption_native_capture as _baseline
from test_caption_native_capture import raw

from scripts.attended_native_admission import digest
from scripts.attended_pcm_admission import PCM_CHECKS, PcmAdmission


@pytest.fixture
def base():
    case = _baseline.AdmissionTests(methodName="runTest")
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def make_authority(base, consumer="offline", review_change=None):
    proofs = {check: raw(dict(schema="caption-native-pcm-proof-v1", candidate=base.authority.candidate,
                             base_review_sha256=base.authority.review_sha256, consumer=consumer,
                             check=check, scope="physical", result="PASS", provider_calls=0))
              for check in PCM_CHECKS}
    review = dict(schema="caption-native-pcm-review-v1", candidate=base.authority.candidate,
                  base_review_sha256=base.authority.review_sha256, consumer=consumer,
                  provider_authority_sha256="e" * 64 if consumer == "app-asr" else None,
                  proofs={key: digest(value) for key, value in proofs.items()})
    if review_change:
        review_change(review, proofs)
    encoded = raw(review)
    return PcmAdmission(base.authority, encoded, digest(encoded), proofs)


def issue(base, authority, **overrides):
    # Base permission, distinct PCM permission; the latter can only narrow expiry.
    base_grant, runtime = base.grant()
    time_limit = json.loads(base_grant)["expires_unix_ns"] - 1_000_000
    base_permit = base.authority.issue(base_grant, digest(base_grant), runtime, base.c)
    grant = dict(schema="caption-native-pcm-grant-v1", candidate=base.authority.candidate,
                 review_sha256=authority.review_sha256, base_grant_sha256=digest(base_grant), programme=base.j.programme,
                 ledger_tail=base.j.tail, session_id="fixture-session", generation=3,
                 epoch="12" * 16, asr_sample_rate=16000, consumer=authority.consumer,
                 expires_unix_ns=time_limit,
                 provider_authority_sha256=authority.provider_authority_sha256)
    grant.update(overrides)
    encoded = raw(grant)
    return authority.issue(encoded, digest(encoded), base.c, base_permit)


def consume(base, authority, permit, **overrides):
    kwargs = dict(session_id="fixture-session", generation=3, sample_rate=16000, consumer=authority.consumer)
    kwargs.update(overrides)
    return authority.consume(permit, base.c, **kwargs)


def test_pcm_permit_requires_both_trust_domains_and_consumes_once(base):
    authority = make_authority(base)
    permit = issue(base, authority)
    launch = consume(base, authority, permit)
    assert launch["epoch"] == "12" * 16
    assert launch["generation"] == 3
    assert base.j.charged == 0  # No opener or budget/debit claimed by unit admission.
    with pytest.raises(RuntimeError, match="not_admitted"):
        consume(base, authority, permit)


@pytest.mark.parametrize("overrides", [
    dict(generation=4), dict(generation=True), dict(session_id="other-session"),
    dict(sample_rate=48000), dict(consumer="app-asr"),
])
def test_wrong_session_generation_rate_consumer_burns_pcm_permit(base, overrides):
    authority = make_authority(base)
    permit = issue(base, authority)
    with pytest.raises(RuntimeError, match="session_binding"):
        consume(base, authority, permit, **overrides)
    with pytest.raises(RuntimeError, match="not_admitted"):
        consume(base, authority, permit)
    assert base.j.charged == 0


@pytest.mark.parametrize("overrides", [
    dict(epoch="0" * 32), dict(asr_sample_rate=48000), dict(generation=False),
    dict(ledger_tail="c" * 64), dict(provider_authority_sha256="e" * 64),
    dict(expires_unix_ns=0), dict(candidate="c" * 40),
])
def test_pcm_grant_binding_rejects_before_any_debit(base, overrides):
    authority = make_authority(base)
    with pytest.raises(RuntimeError, match="grant_binding"):
        issue(base, authority, **overrides)
    assert base.j.charged == 0


def test_app_asr_authority_reference_is_independently_review_pinned(base):
    authority = make_authority(base, consumer="app-asr")
    with pytest.raises(RuntimeError, match="grant_binding"):
        issue(base, authority, provider_authority_sha256="f" * 64)


def test_mock_proof_scope_and_digest_cannot_be_replaced_by_unit_pass(base):
    def change(review, proofs):
        proof = json.loads(proofs["stop_drain"])
        proof["scope"] = "software"
        proofs["stop_drain"] = raw(proof)
        review["proofs"]["stop_drain"] = digest(proofs["stop_drain"])
    with pytest.raises(RuntimeError, match="physical_proof_required"):
        make_authority(base, review_change=change)
    with pytest.raises(RuntimeError, match="base_admission"):
        PcmAdmission(None, b"", "a" * 64, {})


def test_expiry_and_parent_change_refused_at_consumption(base):
    authority = make_authority(base)
    permit = issue(base, authority)
    with patch("scripts.attended_pcm_admission.time.time_ns", return_value=2**63):
        with pytest.raises(RuntimeError, match="session_binding"):
            consume(base, authority, permit)
    assert base.j.charged == 0


def test_discard_capture_challenge_cannot_debit_pcm_domain(base):
    cap, channel, peer = base.c.session(base.authority.candidate)
    try:
        receipt = base.c.offer(cap, channel, 2000)
        challenge = dict(event="capture_budget_ready", challenge="d" * 64,
                         ceiling_ms=2000, anchor_continuous_ticks=1000000000, timebase_numer=1, timebase_denom=1)
        with pytest.raises(ValueError):
            base.c.prepare_pcm_budget(cap, channel, receipt, challenge, valid_until_ticks=3000000000, expires_unix_ns=2**63)
        assert base.j.charged == 0
    finally:
        peer.close()
        base.c.revoke(cap)


def test_pcm_budget_reserves_in_journal_before_wire_and_revoke_retains_hold(base):
    cap, channel, peer = base.c.session(base.authority.candidate)
    try:
        receipt = base.c.offer(cap, channel, 2000)
        challenge = dict(event="capture_pcm_budget_ready", challenge="d" * 64,
                         ceiling_ms=2000, anchor_continuous_ticks=1000000000, timebase_numer=1, timebase_denom=1)
        reservation, wire = base.c.prepare_pcm_budget(cap, channel, receipt, challenge, valid_until_ticks=3000000000, expires_unix_ns=2**63)
        assert wire[:8] == b"CBPC0002"
        assert len(wire) == 72 and base.j.active is not None and base.j.charged == reservation.reserved_ms
    finally:
        peer.close()
        base.c.revoke(cap)
    assert base.j.active is not None


def test_pcm_cannot_substitute_another_base_device_duration_or_runtime_grant(base):
    authority = make_authority(base)
    permit = issue(base, authority, base_grant_sha256="f" * 64)
    with pytest.raises(RuntimeError, match="runtime_binding"):
        consume(base, authority, permit)
    assert base.j.charged == 0
