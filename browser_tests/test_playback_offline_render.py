"""Real browser digital rendering, no realtime output/capture/provider access."""
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[1]


def test_actual_offline_engine_preserves_pcm_and_observes_first_submission(page: Page):
    page.route("**/*", lambda route: route.abort())
    page.goto("about:blank")
    page.evaluate("""() => {
        window.forbiddenAudioCalls = 0;
        const deny = () => { forbiddenAudioCalls++; throw Error('realtime audio forbidden'); };
        window.AudioContext = deny; window.webkitAudioContext = deny;
        HTMLMediaElement.prototype.play = deny;
        Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: deny}});
    }""")
    for path in ["app/static/pcm-player.js", "evaluations/speech_timing/browser_probe.cjs",
                 "evaluations/speech_timing/generated_fixture.cjs",
                 "evaluations/speech_timing/offline_render.js"]:
        page.add_script_tag(path=str(ROOT / path))
    report = page.evaluate("observeOfflinePlayback()")
    assert report["real_browser"] and not report["acoustic_measured"]
    assert not report["realtime_underruns_measured"]
    assert report["acceptance"] == "not_evaluated"
    assert len(report["rows"]) == 4
    for row in report["rows"]:
        assert row["starts"] == row["completes"] == 1
        assert not row["failure"]
        assert row["max_error"] < 1e-6 and row["outside_peak"] < 1e-6
        assert row["remaining_bytes"] == row["remaining_clips"] == 0
        assert row["probe"]["completed"] and row["probe"]["rejected"] == 0
        assert len(row["probe"]["chunks"]) == 7
    assert page.evaluate("forbiddenAudioCalls") == 0
    # No speed GO, acoustic or native Safari claim follows from this contract.
