"""Confirmed session terminology edits; no provider calls or diagnostic content."""

from __future__ import annotations

import unicodedata

from app.glossary import MAX_TERMINOLOGY_CHANGES, TerminologyRevision, parse_glossary

STALE_ERROR = "Terminology changed. Review the current terms and try again."
LIMIT_ERROR = "This session reached 100 terminology changes. Start a new session to add more."


def initialize(session, glossary) -> None:
    session.glossary = glossary
    session.terminology_version = 1 if glossary else 0
    session.terminology_history = [TerminologyRevision(
        version=session.terminology_version, glossary=glossary, action="initial"
    )]
    session.terminology_undo_versions = []


def state(session) -> dict:
    return {
        "session_id": session.id,
        "glossary": session.glossary.model_dump(mode="json", exclude_defaults=True)
        if session.glossary else None,
        "terminology_version": session.terminology_version,
        "terminology_can_undo": bool(session.terminology_undo_versions),
        "terminology_changes": max(0, len(session.terminology_history) - 1),
    }


def change(manager, message: dict, *, undo: bool = False) -> None:
    session = manager.session
    if session.status not in {"listening", "reconnecting"}:
        raise ValueError("Terminology can be changed while listening.")
    if (message.get("session_id") != session.id
            or type(message.get("expected_version")) is not int
            or message["expected_version"] != session.terminology_version
            or message.get("target_language") != session.target_language):
        raise ValueError(STALE_ERROR)
    if len(session.terminology_history) >= MAX_TERMINOLOGY_CHANGES + 1:
        raise ValueError(LIMIT_ERROR)

    undo_of = None
    caption_seq = None
    if undo:
        if not session.terminology_undo_versions:
            raise ValueError("There is no terminology change to undo.")
        undo_of = session.terminology_undo_versions[-1]
        previous = next(rev for rev in session.terminology_history if rev.version == undo_of - 1)
        glossary = previous.glossary
    else:
        glossary = parse_glossary(message.get("glossary"), session.target_language)
        caption_seq = message.get("caption_seq")
        if caption_seq is not None:
            segment = next((seg for seg in session.segments if seg.seq == caption_seq), None)
            if (type(caption_seq) is not int or segment is None
                    or caption_seq > session.highest_pushed_seq):
                raise ValueError("Choose a displayed caption to correct.")
            old_entries = session.glossary.entries if session.glossary else ()
            changed = [entry for entry in glossary.entries if entry not in old_entries] if glossary else []
            source_text = unicodedata.normalize("NFC", segment.source_text).casefold()
            if any(entry.source.casefold() not in source_text for entry in changed):
                raise ValueError("Choose a source term that occurs in the displayed caption.")
        if glossary == session.glossary:
            raise ValueError("No terminology changes to save.")

    revision = TerminologyRevision(
        version=session.terminology_version + 1, glossary=glossary,
        action="undo" if undo else "save", caption_seq=caption_seq, undo_of=undo_of,
    )
    undo_versions = list(session.terminology_undo_versions)
    if undo:
        undo_versions.pop()
    else:
        undo_versions.append(revision.version)
    # Persist before acknowledging so refresh/recovery cannot lose a confirmed edit.
    if manager._journal is not None:
        manager._journal.record_terminology(revision, undo_versions)
    session.terminology_history.append(revision)
    session.terminology_version = revision.version
    session.terminology_undo_versions = undo_versions
    session.glossary = glossary
    manager._emit("terminology_updated", state(session))


def restore_revision(session, raw: object, versions: object) -> None:
    """Recover only a valid sequential revision and its exact undo stack."""
    revision = TerminologyRevision.model_validate(raw)
    if len(session.terminology_history) >= MAX_TERMINOLOGY_CHANGES + 1:
        raise ValueError("Invalid terminology history.")
    expected_undo = list(session.terminology_undo_versions)
    if not session.terminology_history:
        if (revision.action != "initial" or revision.version != (1 if revision.glossary else 0)
                or revision.caption_seq is not None or revision.undo_of is not None):
            raise ValueError("Invalid initial terminology revision.")
    else:
        if revision.version != session.terminology_version + 1:
            raise ValueError("Invalid terminology revision order.")
        if revision.action == "save" and revision.undo_of is None:
            expected_undo.append(revision.version)
        elif revision.action == "undo" and expected_undo and revision.caption_seq is None:
            if revision.undo_of != expected_undo.pop():
                raise ValueError("Invalid terminology undo.")
            previous = next(r for r in session.terminology_history if r.version == revision.undo_of - 1)
            if revision.glossary != previous.glossary:
                raise ValueError("Invalid terminology undo snapshot.")
        else:
            raise ValueError("Invalid terminology action.")
    if (not isinstance(versions, list) or versions != expected_undo
            or any(type(v) is not int for v in versions)):
        raise ValueError("Invalid terminology undo stack.")
    session.terminology_history.append(revision)
    session.terminology_version = revision.version
    session.terminology_undo_versions = expected_undo
    session.glossary = revision.glossary
