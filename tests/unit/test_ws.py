"""WebSocket lifecycle regression tests."""

import app.ws as ws_mod
from app.ws import _handle_latency_ack, _is_expected_websocket_disconnect


def test_superseded_websocket_runtime_error_is_expected_disconnect() -> None:
    error = RuntimeError("WebSocket is not connected. Need to call accept first.")
    assert _is_expected_websocket_disconnect(error)


def test_unrelated_runtime_error_is_not_expected_disconnect() -> None:
    assert not _is_expected_websocket_disconnect(RuntimeError("unexpected failure"))


class _AckSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def observe_render_ack(self, seq: int) -> None:
        self.calls.append(("render", seq))

    def observe_tts_playback_start(self, seq: int) -> None:
        self.calls.append(("tts_start", seq))

    def observe_tts_playback_complete(self, seq: int) -> None:
        self.calls.append(("tts_complete", seq))


def test_latency_ack_routes_valid_seq_and_rejects_bad_seq() -> None:
    sink = _AckSink()
    previous = ws_mod.manager
    ws_mod.manager = sink
    try:
        _handle_latency_ack({"seq": 4}, "render")
        _handle_latency_ack({"seq": 4}, "tts_start")
        _handle_latency_ack({"seq": 4}, "tts_complete")
        _handle_latency_ack({"seq": "4"}, "render")
        _handle_latency_ack({"seq": True}, "tts_start")
        _handle_latency_ack({}, "tts_complete")
    finally:
        ws_mod.manager = previous
    assert sink.calls == [("render", 4), ("tts_start", 4), ("tts_complete", 4)]
