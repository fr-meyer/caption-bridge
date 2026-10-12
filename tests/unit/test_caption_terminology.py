"""Offline regression tests for confirmed, versioned caption terminology."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.ws as ws
from app import terminology
from app.exporter import export_session
from app.glossary import ERROR_MESSAGE, effective_source, parse_glossary
from app.journal import SessionJournal, run_recovery
from app.state import Segment, SessionManager
from app.translate import TranslationDispatcher
from tests.unit.test_glossary import config_at


def listening(path: Path, entries=None) -> SessionManager:
    manager = SessionManager(config_at(path))
    terminology.initialize(manager.session, parse_glossary(entries or [], "en"))
    manager.session.status = "listening"
    manager.set_journal(SessionJournal(manager.session.id, manager.config))
    manager._journal.record_session_started()
    manager._journal.record_terminology(manager.session.terminology_history[0], [])
    segment = Segment(seq=1, source_text="A misheard protocol term.", segment_kind="complete",
                      translated_text="Original result.", translation_status="done")
    manager.session.segments.append(segment)
    manager.session.highest_pushed_seq = 1
    manager.session.next_seq = 2
    manager._journal.record_segment_created(segment)
    manager._journal.record_translation_updated(segment)
    return manager


def message(manager, entries=None, **extra):
    return {"type": "update_terminology", "session_id": manager.session.id,
            "expected_version": manager.session.terminology_version,
            "target_language": manager.session.target_language, "glossary": entries, **extra}


def test_caption_creation_edit_remove_and_multistep_undo_preserve_original(tmp_path):
    manager = listening(tmp_path)
    original = manager.session.segments[0].model_dump()
    events = []
    manager.subscribe(events.append)
    pair = {"source": "protocol", "preferred": "Protocol-X"}
    terminology.change(manager, message(manager, [pair], caption_seq=1))
    terminology.change(manager, message(manager, [{**pair, "preferred": "Protocol-Y"}]))
    terminology.change(manager, message(manager, []))
    assert manager.session.glossary is None
    for expected in ["Protocol-Y", "Protocol-X", None]:
        terminology.change(manager, message(manager), undo=True)
        assert (manager.session.glossary.entries[0].preferred if manager.session.glossary else None) == expected
    assert not manager.session.terminology_undo_versions
    assert manager.session.terminology_version == 6
    assert manager.session.segments[0].model_dump() == original
    assert all(event["type"] == "terminology_updated" for event in events)
    assert manager.session.terminology_history[1].caption_seq == 1


@pytest.mark.parametrize("extra", [
    {"session_id": "obsolete"}, {"expected_version": True}, {"expected_version": 99},
    {"target_language": "fr"}, {"caption_seq": True}, {"caption_seq": 999},
])
def test_stale_or_invalid_caption_edits_do_not_mutate(tmp_path, extra):
    manager = listening(tmp_path)
    before = manager.session.model_dump()
    with pytest.raises(ValueError):
        terminology.change(manager, message(manager, [{"source": "protocol", "preferred": "X"}], **extra))
    assert manager.session.model_dump() == before


def test_caption_term_must_be_present_and_errors_never_echo_content(tmp_path, monkeypatch, caplog):
    manager = listening(tmp_path)
    monkeypatch.setattr(ws, "manager", manager)
    queue = asyncio.Queue()
    private = "PRIVATE_CORRECTION_SENTINEL"
    ws._handle_terminology(message(manager, [{"source": private, "preferred": "X"}], caption_seq=1),
                          queue, ws._OutboundObsState())
    event, _ = queue.get_nowait()
    assert private not in event["message"]
    ws._handle_terminology(message(manager, [{"source": private, "preferred": "x" * 81}]),
                          queue, ws._OutboundObsState())
    event, _ = queue.get_nowait()
    assert event["message"] == ERROR_MESSAGE
    assert manager.session.terminology_version == 0
    assert private not in caplog.text


def test_journal_failure_keeps_previous_version_and_allows_retry(tmp_path, monkeypatch):
    manager = listening(tmp_path)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(manager._journal, "record_terminology", lambda *_: (_ for _ in ()).throw(OSError("private")))
    queue = asyncio.Queue()
    ws._handle_terminology(message(manager, [{"source": "protocol", "preferred": "X"}]),
                          queue, ws._OutboundObsState())
    event, _ = queue.get_nowait()
    assert event["message"] == "Terminology could not be saved. Try again."
    assert manager.session.glossary is None
    assert manager.session.terminology_version == 0


def test_source_replacements_do_not_cascade_and_are_language_scoped():
    glossary = parse_glossary([
        {"source": "protocol", "preferred": "corrected", "kind": "source"},
        {"source": "corrected", "preferred": "chained", "kind": "source"},
    ], "en")
    assert effective_source("PROTOCOL corrected", glossary, "en") == "corrected chained"
    assert effective_source("PROTOCOL corrected", glossary, "fr") == "PROTOCOL corrected"
    special = parse_glossary([{"source": "i", "preferred": "I", "kind": "source"}], "en")
    assert effective_source("İ", special, "en") == "I"


def test_normalized_source_term_and_invalid_recovery_stack(tmp_path):
    manager = listening(tmp_path)
    manager.session.segments[0].source_text = "A cafe\u0301 term."
    terminology.change(manager, message(manager, [{"source": "café", "preferred": "cafe"}], caption_seq=1))
    before = manager.session.model_dump()
    with pytest.raises(ValueError, match="undo stack"):
        terminology.restore_revision(manager.session, {
            "version": 2, "action": "save", "glossary": None,
        }, [1, True])
    assert manager.session.model_dump() == before


def test_dispatch_freezes_input_metadata_through_edit_undo_and_model_change(tmp_path, caplog):
    async def scenario():
        manager = listening(tmp_path)
        manager.config.translation_repair_max_attempts = 0
        terms = [
            {"source": "misheard", "preferred": "corrected", "kind": "source"},
            {"source": "protocol", "preferred": "PRIVATE_RENDERING_SENTINEL"},
        ]
        terminology.change(manager, message(manager, terms, caption_seq=1))
        provider = SimpleNamespace(name="synthetic", translate=AsyncMock(return_value="Synthetic translation."))
        dispatcher = TranslationDispatcher(manager, manager.config, provider=provider)
        segment = Segment(seq=2, source_text="A misheard protocol term.", segment_kind="complete")
        manager.session.segments.append(segment)
        manager._journal.record_segment_created(segment)
        dispatcher.dispatch(segment, [], manager.session.id, "en")
        terminology.change(manager, message(manager), undo=True)
        manager.config.translate_model = "another-synthetic-model"
        await dispatcher.drain()
        content = json.dumps(provider.translate.call_args.kwargs["messages"])
        assert "A corrected protocol term." in content
        assert "PRIVATE_RENDERING_SENTINEL" in content
        assert segment.source_text == "A misheard protocol term."
        assert segment.effective_source_text == "A corrected protocol term."
        assert segment.terminology_version == 1
        assert segment.terminology_status == "active"
        assert segment.terminology.entries[1].preferred == "PRIVATE_RENDERING_SENTINEL"
        assert manager.session.glossary is None
        assert manager.session.segments[0].translated_text == "Original result."
        diagnostic = json.dumps(manager.get_snapshot()["runtime_metrics"])
        diagnostic += json.dumps(manager._reliability.build_session_record(manager.session))
        assert "PRIVATE_RENDERING_SENTINEL" not in diagnostic + caplog.text
        assert "corrected" not in diagnostic
        return manager
    manager = asyncio.run(scenario())
    data = json.loads((Path(export_session(manager.session, manager.config)) / "transcript.json").read_text())
    assert data["segments"][1]["source_text"] == "A misheard protocol term."
    assert data["segments"][1]["effective_source_text"] == "A corrected protocol term."
    assert data["segments"][1]["terminology_version"] == 1
    assert data["terminology_history"][1]["caption_seq"] == 1
    assert data["terminology_history"][2]["undo_of"] == 1
    result = run_recovery(manager.config)
    recovered = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert recovered["terminology_history"] == data["terminology_history"]
    assert recovered["segments"][1]["terminology"] == data["segments"][1]["terminology"]
    assert recovered["segments"][1]["effective_source_text"] == "A corrected protocol term."
    assert recovered["segments"][0]["translated_text"] == "Original result."


def test_dispatch_uses_canonical_segment_and_language_pause_metadata(tmp_path):
    async def scenario():
        manager = listening(tmp_path, [{"source": "protocol", "preferred": "corrected", "kind": "source"}])
        dispatcher = TranslationDispatcher(manager, manager.config, provider=SimpleNamespace(name="synthetic"))
        segment = Segment(seq=2, source_text="protocol", segment_kind="complete")
        async def worker(actual, *args):
            assert actual is segment
            # PR64 attaches resolved-model, usage and finish metadata to this object.
            actual.failure_reason = "synthetic-canonical-metadata"
        dispatcher._translate_task = worker
        dispatcher.dispatch(segment, [], manager.session.id, "fr")
        await dispatcher.drain()
        assert segment.terminology_status == "paused"
        assert segment.terminology is None
        assert segment.effective_source_text == "protocol"
        assert segment.failure_reason == "synthetic-canonical-metadata"
        dispatcher.dispatch(segment, [], manager.session.id, "en")
        await dispatcher.drain()
        assert segment.terminology_status == "active"
        assert segment.effective_source_text == "corrected"
    asyncio.run(scenario())


def test_language_pause_resume_refresh_and_session_reset(tmp_path):
    manager = listening(tmp_path)
    terminology.change(manager, message(manager, [{"source": "protocol", "preferred": "X"}]))
    manager.set_target_language("fr")
    assert effective_source("protocol", manager.session.glossary, "fr") == "protocol"
    assert manager.get_snapshot()["glossary"]["target_language"] == "en"
    manager.set_target_language("en")
    snapshot = manager.get_snapshot()
    assert snapshot["session_id"] == manager.session.id
    assert snapshot["terminology_version"] == 1
    assert snapshot["terminology_can_undo"] is True
    asyncio.run(manager.reset())
    assert manager.session.terminology_version == 0
    assert manager.session.terminology_history == []


def test_revision_limit_is_bounded_for_saves_and_undo(tmp_path):
    manager = listening(tmp_path)
    for index in range(100):
        terminology.change(manager, message(manager, [{"source": "protocol", "preferred": str(index)}]))
    assert len(manager.session.terminology_history) == 101
    for undo in [False, True]:
        with pytest.raises(ValueError, match="100 terminology changes"):
            terminology.change(manager, message(manager, []), undo=undo)


def test_changed_terms_at_end_and_malformed_recovery_are_content_free(tmp_path, caplog):
    manager = listening(tmp_path)
    manager.session.status = "session_ended"
    with pytest.raises(ValueError, match="while listening"):
        terminology.change(manager, message(manager, []))
    manager._journal._write({"type": "terminology_revision", "revision": {
        "version": True, "action": "save", "glossary": "PRIVATE_RECOVERY_SENTINEL"
    }, "undo_versions": []})
    result = run_recovery(manager.config)
    assert result.notice.status == "success"
    assert "PRIVATE_RECOVERY_SENTINEL" not in caplog.text
