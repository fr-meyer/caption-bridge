"""Provider answer extraction excludes thinking and preserves only caption text."""

from __future__ import annotations

from types import SimpleNamespace

from app.providers import extract_translation_text


def test_chunked_response_keeps_text_only() -> None:
    content = [
        SimpleNamespace(type="thinking", thinking="private reasoning"),
        SimpleNamespace(type="text", text="This result is "),
        {"type": "text", "text": "statistically significant."},
    ]
    assert extract_translation_text(content) == (
        "This result is statistically significant."
    )
    assert extract_translation_text("  Plain caption.  ") == "Plain caption."
    assert extract_translation_text([{"type": "thinking", "thinking": "x"}]) == ""
    assert extract_translation_text(None) == ""
