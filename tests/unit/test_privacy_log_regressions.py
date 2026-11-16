"""Exercise real failure paths without provider or native device operations."""

import asyncio
import logging
import sys
from types import SimpleNamespace

import pytest

from app import readiness, transcribe


@pytest.mark.parametrize("failure_stage", ["connect", "close"])
def test_deferred_connection_cleanup_log_is_content_free(caplog, failure_stage):
    sensitive_error = type("SECRET_PROVIDER_CLASS", (RuntimeError,), {})

    async def close():
        if failure_stage == "close":
            raise sensitive_error("SECRET provider response and device identifier")

    async def connect():
        if failure_stage == "connect":
            raise sensitive_error("SECRET provider response and device identifier")
        return SimpleNamespace(close=close)

    async def scenario():
        await transcribe._dispose_pending_connection(asyncio.create_task(connect()))

    with caplog.at_level(logging.DEBUG, logger=transcribe.__name__):
        asyncio.run(scenario())
    records = [record for record in caplog.records if record.name == transcribe.__name__]
    assert len(records) == 1
    assert records[0].getMessage() == "ASR connection cleanup failed"
    assert not records[0].args and not records[0].exc_info and not records[0].stack_info
    assert "SECRET" not in caplog.text


def test_microphone_query_failure_log_is_content_free(monkeypatch, caplog):
    sensitive_error = type("SECRET_DEVICE_CLASS", (RuntimeError,), {})

    def fail_query():
        raise sensitive_error("SECRET native device identifier")

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=fail_query))
    with caplog.at_level(logging.DEBUG, logger=readiness.__name__):
        result = readiness._check_mic_available()
    assert not result.ready and result.detail == "No input device found"
    records = [record for record in caplog.records if record.name == readiness.__name__]
    assert len(records) == 1
    assert records[0].getMessage() == "Microphone availability check failed"
    assert not records[0].args and not records[0].exc_info and not records[0].stack_info
    assert "SECRET" not in caplog.text
