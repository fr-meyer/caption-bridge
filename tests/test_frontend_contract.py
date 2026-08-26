"""Static safety contracts for the browser client."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "app.js"
INDEX_HTML = ROOT / "app" / "static" / "index.html"


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


def test_build_identity_is_visible_and_fetched() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")
    assert 'id="build-identity"' in html
    assert 'fetch("/version"' in source
    assert "loadBuildIdentity" in source


def test_icon_controls_have_accessible_names() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for label in (
        'aria-label="Settings"',
        'aria-label="Mute translated speech"',
        'aria-label="Decrease caption size"',
        'aria-label="Increase caption size"',
        'aria-label="Toggle fullscreen"',
        'aria-label="Close settings"',
        'aria-label="Target language"',
    ):
        assert label in html
