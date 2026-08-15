"""Static safety contracts for the browser client."""

from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


def test_tts_audio_unlock_is_document_scoped() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert 'ttsAudioUnlocked: false' in source
    assert 'sessionStorage.getItem("ttsAudioUnlocked")' not in source
    assert 'sessionStorage.setItem("ttsAudioUnlocked"' not in source


def test_tts_audio_unlock_still_requires_explicit_user_action() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert 'els.enableAudioBtn.addEventListener("click"' in source
    assert 'appState.ttsAudioUnlocked = true;' in source
    assert 'send({ type: "tts_audio_enabled" });' in source
