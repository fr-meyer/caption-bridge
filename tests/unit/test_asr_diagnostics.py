"""Safe ASR correlation without a provider, device or retained content."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace

from app.asr_diagnostics import AsrDiagnostics
from app.reconnect import classify_reconnect_failure
from app.transcribe import AsrStreamError


def rows(caplog):
    return [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records
            if r.name == "app.asr_diagnostics"]


def test_failure_is_timestamped_allowlisted_and_deduplicated_per_run_attempt(caplog):
    caplog.set_level(logging.INFO)
    diagnostic = AsrDiagnostics()
    error = AsrStreamError("provider_error")
    error.__cause__ = OSError("SECRET response, transcript, credential and device")
    info = classify_reconnect_failure(error)
    assert diagnostic.failure(error, attempt_id=3, info=info)
    assert not diagnostic.failure(error, attempt_id=3, info=info)
    diagnostic.new_run()
    assert diagnostic.failure(error, attempt_id=3, info=info)
    events = rows(caplog)
    assert len(events) == 2 and events[0]["run_id"] != events[1]["run_id"]
    assert "SECRET" not in caplog.text
    for event in events:
        assert set(event) == {"schema_version", "at_utc", "event", "run_id", "attempt_id",
                              "attempt", "downtime_ms", "reason", "category", "close_code", "status_code"}
        assert re.fullmatch(r"[a-f0-9]{32}", event["run_id"])
        assert datetime.fromisoformat(event["at_utc"]).utcoffset().total_seconds() == 0
        assert event["event"] == "stream_failure" and event["reason"] == "provider_error"
        assert event["attempt_id"] == 3 and event["category"] == "transport"


def test_invalid_metadata_cannot_copy_exception_or_provider_fields(caplog):
    caplog.set_level(logging.INFO)
    error = RuntimeError("SECRET payload")
    error.reason = "SECRET reason"
    info = SimpleNamespace(category="SECRET category", close_code=True,
                           status_code=987654321, secret="SECRET identifier")
    diagnostic = AsrDiagnostics()
    diagnostic.failure(error, attempt_id=0, info=info)
    event = rows(caplog)[0]
    assert event["reason"] == "transport_error" and event["category"] == "unknown"
    assert event["close_code"] is event["status_code"] is None
    assert "SECRET" not in caplog.text and "RuntimeError" not in caplog.text


def test_wrapped_close_and_http_classification_is_bounded_and_content_free():
    for attr, value, category, recoverable in [
        ("code", 1012, "provider_restart", True),
        ("status_code", 503, "provider_transient", True),
        ("status_code", 401, "provider_configuration", False),
    ]:
        cause = RuntimeError("SECRET provider body")
        setattr(cause, attr, value)
        error = AsrStreamError("send_failed")
        error.__cause__ = cause
        info = classify_reconnect_failure(error)
        assert info.category == category and info.recoverable == recoverable
        assert "SECRET" not in repr(info)
    error = RuntimeError("SECRET")
    error.code, error.status_code = 123456789, "SECRET"
    error.__cause__ = error
    info = classify_reconnect_failure(error)
    assert info.category == "unknown" and info.close_code is info.status_code is None
