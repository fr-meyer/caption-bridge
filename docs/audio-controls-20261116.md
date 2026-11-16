# Audio controls reconciliation, 2026-11-16

## Correct baseline

Current dev is 8d98a0b8d5a81ddfb78ad0ab30ee05de33efa7e9. Its native routing, ASR diagnostics and pitch-preserving WSOLA evaluation supersede stale main-based assumptions. The earlier duplicate routing slice 4decf159f8158fe5ff6dd6aabe5ba5bfcec6116b is preserved only on archive/caption-audio-stale-main-20261116. Do not integrate that commit.

## Actual gaps and disposition

- Native input selection, Start locking, revalidation and shared-context sink routing already exist. Reuse InputDevices and CaptionAudioDevices, not a new endpoint/token protocol.
- Existing revealOutputs fallback opened getUserMedia merely to reveal speaker labels. This violates the approved no-browser-microphone inventory constraint. Removed that permission-stream fallback. Output chooser remains selectAudioOutput where supported; already-permitted enumerateDevices outputs remain usable with setSinkId. Otherwise use system/browser sound settings. No microphone is opened for output discovery.
- Existing complete-clip pitch-preserving WSOLA evaluation and worker/memory contracts live in speed-evaluation/pitch. Keep normal production speed 1x. This lane does not replace or silently promote that prototype. Human listening, actual device routing and shared-player speed integration acceptance remain open.
- ASR frontend adaptation awaits reliability lane's revised event contract on this actual dev baseline. Existing readiness UI/diagnostics must be preserved.

## Validation

Local small checks: node --check app/static/audio-devices.js; direct synthetic Node no-capture fallback assertion PASS; Python compilation of amended browser contract; git diff --check. No dependencies installed, hardware opened, provider calls, runtime changes or expensive suites.

Hosted CI requested: uv run pytest tests/unit/test_audio_devices.py; uv run pytest browser_tests/test_audio_devices.py browser_tests/test_pcm_player.py browser_tests/test_speech_catch_up.py; existing pitch Node contracts from CI, then full exact-integrated-head mandatory jobs. Existing physical and listening evidence is historical, not current-candidate acceptance.
