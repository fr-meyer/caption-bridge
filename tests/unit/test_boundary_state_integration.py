"""Integration coverage for semantic boundary decisions and session state."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.boundary import BoundaryDetector
from app.config import AppConfig
from app.state import SessionManager


@patch("asyncio.get_running_loop")
def test_deferred_fragment_stays_partial_until_merged(
    mock_loop: MagicMock,
) -> None:
    config = AppConfig(_env_file=None)
    manager = SessionManager(config)
    events: list[dict[str, object]] = []
    manager.subscribe(events.append)
    detector = BoundaryDetector(
        pause_timeout_s=config.pause_timeout_ms / 1000,
        on_partial=manager.update_partial,
        on_finalize=manager.finalize_segment,
        fragment_merge_enabled=config.fragment_merge_enabled,
        fragment_max_hold_s=config.fragment_max_hold_ms / 1000,
        min_segment_chars=config.fragment_min_chars,
        min_segment_tokens=config.fragment_min_tokens,
    )

    fragment = "이 결과는 통계적으로 유의미하지만"
    detector.push(fragment)
    detector._on_pause_timeout()

    assert manager.session.source_partial == fragment
    assert manager.session.segments == []
    assert any(
        event == {"type": "source_partial", "text": fragment}
        for event in events
    )

    continuation = " 추가 검증이 필요합니다."
    detector.push(continuation)

    assert manager.session.source_partial == ""
    assert len(manager.session.segments) == 1
    segment = manager.session.segments[0]
    assert segment.seq == 1
    assert segment.source_text == fragment + continuation
    assert segment.segment_kind == "complete"
