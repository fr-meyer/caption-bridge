"""WebSocket lifecycle regression tests."""

from app.ws import _is_expected_websocket_disconnect


def test_superseded_websocket_runtime_error_is_expected_disconnect() -> None:
    error = RuntimeError("WebSocket is not connected. Need to call accept first.")
    assert _is_expected_websocket_disconnect(error)


def test_unrelated_runtime_error_is_not_expected_disconnect() -> None:
    assert not _is_expected_websocket_disconnect(RuntimeError("unexpected failure"))
