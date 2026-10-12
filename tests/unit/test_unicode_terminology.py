"""Unicode caption corrections must be accepted and applied consistently offline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import terminology
from app.exporter import export_session
from app.glossary import (
    ERROR_MESSAGE,
    Glossary,
    add_to_messages,
    effective_source,
    parse_glossary,
)
from app.journal import SessionJournal, run_recovery
from app.state import Segment, SessionManager
from app.translate import TranslationDispatcher
from tests.unit.test_caption_terminology import listening, message
from tests.unit.test_glossary import config_at


@pytest.mark.parametrize(("caption", "term"), [
    ("Straße", "STRASSE"), ("STRASSE", "Straße"), ("STRAẞE", "strasse"),
    ("ﬃ", "ffi"), ("FFI", "ﬃ"), ("Σςσ", "σσσ"),
    ("cafe\u0301", "CAFÉ"), ("İ", "i"), ("ı", "I"), ("I", "İ"),
    ("i\u0307", "İ"), ("İ", "i\u0307"), ("i\u0307", "i"), ("ı\u0307", "I"),
    ("i\u0307\u0307", "İ\u0307"), ("İ\u0307", "i\u0307\u0307"),
    ("i\u0307\u0307\u0307", "İ\u0307\u0307"),
    ("ﬁ\u0307", "ﬁ\u0307"), ("ﬃ\u0307", "ﬃ\u0307"), ("ﬁ\u0307", "FI\u0307"),
    ("K", "k"), ("ſ", "S"), ("A+B", "a+b"),
])
def test_saved_caption_correction_applies_to_whole_unicode_span(tmp_path, caption, term):
    manager = listening(tmp_path)
    manager.session.segments[0].source_text = caption
    original = manager.session.segments[0].model_dump()
    terminology.change(manager, message(manager, [
        {"source": term, "preferred": "replacement", "kind": "source"},
    ], caption_seq=1))
    assert manager.session.terminology_version == 1
    assert effective_source(caption, manager.session.glossary, "en") == "replacement"
    assert effective_source(caption, manager.session.glossary, "fr") == caption
    assert manager.session.segments[0].model_dump() == original


@pytest.mark.parametrize(("caption", "term"), [("ß", "s"), ("ﬃ", "f"), ("ﬃ", "ff")])
def test_partial_expanded_letter_is_rejected_without_revision_or_journal_change(
    tmp_path, caption, term,
):
    manager = listening(tmp_path)
    manager.session.segments[0].source_text = caption
    before = manager.session.model_dump()
    journal_before = manager._journal._path.read_bytes()
    with pytest.raises(ValueError, match="occurs in the displayed caption"):
        terminology.change(manager, message(manager, [
            {"source": term, "preferred": "replacement", "kind": "source"},
        ], caption_seq=1))
    assert manager.session.model_dump() == before
    assert manager._journal._path.read_bytes() == journal_before
    # A session-wide saved rule also cannot replace part of a folded letter.
    glossary = parse_glossary([{"source": term, "preferred": "X", "kind": "source"}], "en")
    assert effective_source(caption, glossary, "en") == caption


def test_longest_complete_overlap_and_replacements_never_cascade():
    glossary = parse_glossary([
        {"source": "ffis", "preferred": "invalid-partial", "kind": "source"},
        {"source": "ffi", "preferred": "A", "kind": "source"},
        {"source": "STRASSE", "preferred": "road", "kind": "source"},
        {"source": "road", "preferred": "chained", "kind": "source"},
        {"source": "str", "preferred": "short", "kind": "source"},
    ], "en")
    assert effective_source("ﬃß Straße STRASSE road", glossary, "en") == "Aß road road chained"


@pytest.mark.parametrize("terms", [
    ("Straße", "STRASSE"), ("i", "İ"), ("I", "ı"), ("ﬃ", "FFI"), ("i", "i\u0307"),
])
def test_equivalent_unicode_sources_cannot_create_ambiguous_rules(terms):
    with pytest.raises(ValueError, match=ERROR_MESSAGE):
        parse_glossary([{"source": source, "preferred": str(i)} for i, source in enumerate(terms)], "en")


def test_target_prompt_relevance_uses_same_complete_unicode_matching():
    glossary = parse_glossary([
        {"source": "STRASSE", "preferred": "road"},
        {"source": "i", "preferred": "letter"},
        {"source": "f", "preferred": "absent-partial"},
    ], "en")
    messages = [{"role": "system", "content": "Translate."},
                {"role": "user", "content": "Straße İ ﬃ"}]
    original = json.dumps(messages)
    enriched = json.dumps(add_to_messages(messages, glossary, "en", source_text="Straße İ ﬃ"))
    assert "road" in enriched and "letter" in enriched
    assert "absent-partial" not in enriched
    assert json.dumps(messages) == original


def test_unicode_dispatch_freezes_input_through_undo_export_and_recovery(tmp_path):
    async def scenario():
        manager = listening(tmp_path)
        manager.session.segments[0].source_text = "Straße"
        manager.config.translation_repair_max_attempts = 0
        terminology.change(manager, message(manager, [
            {"source": "STRASSE", "preferred": "road", "kind": "source"},
        ], caption_seq=1))
        provider = SimpleNamespace(name="synthetic", translate=AsyncMock(return_value="Public result."))
        dispatcher = TranslationDispatcher(manager, manager.config, provider=provider)
        segment = Segment(seq=2, source_text="Straße cafe\u0301", segment_kind="complete")
        manager.session.segments.append(segment)
        manager._journal.record_segment_created(segment)
        dispatcher.dispatch(segment, [], manager.session.id, "en")
        terminology.change(manager, message(manager), undo=True)
        await dispatcher.drain()
        assert "road café" in json.dumps(provider.translate.call_args.kwargs["messages"], ensure_ascii=False)
        assert segment.source_text == "Straße cafe\u0301"
        assert segment.effective_source_text == "road café"
        assert segment.terminology_version == 1
        assert segment.terminology.entries[0].source == "STRASSE"
        assert manager.session.glossary is None
        return manager

    manager = asyncio.run(scenario())
    data = json.loads((Path(export_session(manager.session, manager.config)) / "transcript.json").read_text())
    result = run_recovery(manager.config)
    recovered = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert recovered["segments"][1] == data["segments"][1]
    assert data["segments"][1]["source_text"] == "Straße cafe\u0301"
    assert data["segments"][1]["effective_source_text"] == "road café"
    assert recovered["terminology_history"] == data["terminology_history"]


@pytest.mark.parametrize("versioned", [False, True])
def test_recovery_preserves_legacy_matching_equivalent_rules_and_frozen_input(tmp_path, versioned):
    # Pre-fix journals legitimately contain separate i/ı rules. Recovery must
    # export their recorded values without recomputing or rejecting snapshots.
    manager = SessionManager(config_at(tmp_path))
    entries = [{"source": "i", "preferred": "A", "kind": "source"},
               {"source": "ı", "preferred": "B", "kind": "source"}]
    legacy = Glossary.model_validate({"target_language": "en", "entries": entries})
    terminology.initialize(manager.session, legacy)
    manager.set_journal(SessionJournal(manager.session.id, manager.config))
    manager._journal.record_session_started()
    manager._journal.record_glossary(legacy)
    if versioned:
        manager._journal.record_terminology(manager.session.terminology_history[0], [])
    segment = Segment(
        seq=1, source_text="ı", effective_source_text="A", segment_kind="complete",
        terminology=legacy, terminology_version=1, terminology_status="active",
        translation_status="done", translated_text="Recorded result.",
    )
    manager.session.segments.append(segment)
    manager._journal.record_segment_created(segment)
    manager._journal.record_translation_requested(segment)
    manager._journal.record_translation_updated(segment)
    result = run_recovery(manager.config)
    recovered = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert recovered["glossary"] == legacy.model_dump(mode="json", exclude_defaults=True)
    assert recovered["segments"][0]["effective_source_text"] == "A"
    assert recovered["segments"][0]["terminology_version"] == 1
    assert recovered["segments"][0]["terminology"] == legacy.model_dump(mode="json", exclude_defaults=True)
    assert recovered["segments"][0]["source_text"] == "ı"
    assert recovered["segments"][0]["translated_text"] == "Recorded result."
    if versioned:
        assert recovered["terminology_history"] == [
            revision.model_dump(mode="json")
            for revision in manager.session.terminology_history
        ]
    with pytest.raises(ValueError, match=ERROR_MESSAGE):
        parse_glossary(entries, "en")
