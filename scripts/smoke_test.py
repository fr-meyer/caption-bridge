"""Manual smoke test: mic → transcribe → boundary detector → terminal."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from app.audio import AudioCapture
from app.boundary import BoundaryDetector
from app.config import settings
from app.transcribe import transcribe

segments: list[dict] = []
seq_counter = 0


def on_partial(text: str) -> None:
    print(f"\r[PARTIAL] {text}", end="", flush=True)


def on_finalize(text: str) -> None:
    global seq_counter  # noqa: PLW0603
    seq_counter += 1
    segments.append(
        {"seq": seq_counter, "text": text, "timestamp": datetime.now(timezone.utc).isoformat()}
    )
    print(f"\n[FINAL #{seq_counter}] {text}", flush=True)


detector = BoundaryDetector(
    pause_timeout_s=settings.pause_timeout_ms / 1000,
    on_partial=on_partial,
    on_finalize=on_finalize,
)


def on_delta(text: str) -> None:
    detector.push(text)


def on_done() -> None:
    remaining = detector.flush_reconnect_fragment()
    if remaining:
        on_finalize(remaining)
    print("\n--- Transcription stream finished ---", flush=True)


def on_error(err: Exception) -> None:
    print(f"\n[ERROR] {err}", file=sys.stderr, flush=True)


async def main() -> None:
    loop = asyncio.get_running_loop()
    audio = AudioCapture(sample_rate=settings.audio_sample_rate, loop=loop)

    print(
        f"Starting smoke test (rate={settings.audio_sample_rate}, "
        f"pause={settings.pause_timeout_ms}ms, model={settings.transcribe_model})"
    )
    print("Speak into the microphone. Press Ctrl+C to stop.\n")

    audio.start()
    try:
        await transcribe(
            audio_stream=audio.stream(),
            config=settings,
            on_delta=on_delta,
            on_done=on_done,
            on_error=on_error,
        )
    finally:
        audio.stop()
        detector.reset()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n--- Interrupted ---")
        remaining = detector.flush_reconnect_fragment()
        if remaining:
            on_finalize(remaining)
        print(f"\nFinalized {len(segments)} segment(s):")
        for seg in segments:
            print(f"  #{seg['seq']} [{seg['timestamp']}] {seg['text']}")
        print("Goodbye.")
        sys.exit(0)
