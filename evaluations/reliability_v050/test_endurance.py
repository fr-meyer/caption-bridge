"""Finite repeated callback/SDK/epoch checks; no native stream or provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import app.transcribe as transcribe_module
from app.audio import AudioCapture
from app.config import AppConfig

ROOT = Path(__file__).resolve().parents[2]


def receipt(name, data):
    directory = os.environ.get("RELIABILITY_V050_RECEIPTS")
    if directory:
        (Path(directory) / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_ack_helpers():
    spec = importlib.util.spec_from_file_location(
        "endurance_ack_helpers", ROOT / "tests/unit/test_asr_ack_final.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeated_callback_finish_and_stop_release_tail_state():
    async def scenario():
        retained = discarded = 0
        baseline = set(asyncio.all_tasks())
        for cycle in range(64):
            capture = AudioCapture(16000, asyncio.get_running_loop(), max_queue_chunks=1)
            chunks = [(cycle * 3 + i + 1).to_bytes(2, "little") * 4 for i in range(3)]
            capture._enqueue_chunk(chunks[0])
            for chunk in chunks[1:]:
                capture._audio_callback(chunk, 4, {}, False)
            capture.finish_input()
            if cycle % 2:
                capture.stop()
                await asyncio.sleep(0)
                assert [part async for part in capture.stream()] == []
                discarded += 1
            else:
                assert [part async for part in capture.stream()] == chunks
                assert capture._dropped_chunks == 0
                retained += 1
                capture.stop()
            await asyncio.sleep(0)
            if not capture._queue.empty():
                # stop() after completed finish_input leaves one bounded EOF marker.
                assert list(capture._queue._queue) == [None]
                assert [part async for part in capture.stream()] == []
            assert (
                capture._queue.empty()
                and capture._final_chunks == []
                and capture._input_eof_handle is None
            )
            assert capture._sentinel_task is None or capture._sentinel_task.done()
        assert not [t for t in asyncio.all_tasks() - baseline if not t.done()]
        receipt(
            "callback-endurance.json",
            {
                "cycles": 64,
                "tail_preserved_cycles": retained,
                "explicit_stop_discard_cycles": discarded,
                "remaining_tasks": 0,
                "remaining_buffers": 0,
                "native_streams": 0,
                "generated_pcm_only": True,
            },
        )

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_repeated_sdk_ack_done_eof_and_stop_keep_bytes_and_tasks_isolated(monkeypatch):
    helper = load_ack_helpers()
    pcm = b"".join((i % 127 - 63).to_bytes(2, "little", signed=True) for i in range(640))

    async def scenario():
        counts = {"final_only": 0, "delta_done": 0, "eof_without_done": 0, "stop_before_ack": 0}
        baseline = set(asyncio.all_tasks())
        total_appends = 0
        for cycle in range(24):
            mode = tuple(counts)[cycle % 4]
            terminal = (
                [helper.done("Synthetic final.")]
                if mode == "final_only"
                else [
                    {"type": "transcription.text.delta", "text": "Synthetic "},
                    helper.done("Synthetic final."),
                ]
                if mode == "delta_done"
                else [None]
                if mode == "eof_without_done"
                else []
            )
            socket = helper.Socket(terminal)
            helper.install(monkeypatch, socket)
            values = {"ready": 0, "done": 0, "delta": 0, "final": 0, "errors": []}

            async def audio():
                for offset in range(0, len(pcm), 320):
                    yield pcm[offset : offset + 320]

            def add(name, value=1):
                values[name] += value

            task = asyncio.create_task(
                transcribe_module.transcribe(
                    audio(),
                    AppConfig(_env_file=None),
                    on_session_created=lambda: add("ready"),
                    on_done=lambda: add("done"),
                    on_delta=lambda text: add("delta", len(text)),
                    on_final_text=lambda text: add("final", len(text)),
                    on_error=values["errors"].append,
                )
            )
            for _ in range(8):
                await asyncio.sleep(0)
            assert values["ready"] == 0 and socket.frames == []
            if mode == "stop_before_ack":
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                socket.queue.put_nowait(json.dumps(helper.updated()))
                for _ in range(3):
                    await asyncio.sleep(0)
                assert socket.frames == [] and values["ready"] == values["done"] == 0
            else:
                socket.queue.put_nowait(json.dumps(helper.updated()))
                await asyncio.wait_for(task, 1)
                appends = [
                    frame for frame in socket.frames if frame["type"] == "input_audio.append"
                ]
                actual = b"".join(base64.b64decode(frame["audio"]) for frame in appends)
                assert actual == pcm
                total_appends += len(appends)
                assert values["ready"] == 1
                if mode == "eof_without_done":
                    assert (
                        values["done"] == 0 and values["errors"][0].reason == "closed_before_done"
                    )
                else:
                    assert values["done"] == 1 and values["errors"] == []
                    assert (values["delta"], values["final"]) == (
                        (0, 16) if mode == "final_only" else (10, 0)
                    )
            assert socket.closed
            counts[mode] += 1
            for _ in range(3):
                await asyncio.sleep(0)
            assert not [t for t in asyncio.all_tasks() - baseline if not t.done()]
        receipt(
            "sdk-endurance.json",
            {
                "cycles": 24,
                "modes": counts,
                "appended_frames": total_appends,
                "generated_pcm_bytes_per_stream": len(pcm),
                "generated_pcm_sha256": hashlib.sha256(pcm).hexdigest(),
                "all_admitted_pcm_byte_equal": True,
                "no_audio_before_verified_ack": True,
                "no_duplicate_final_admission": True,
                "remaining_tasks": 0,
                "real_provider_calls": 0,
            },
        )

    asyncio.run(asyncio.wait_for(scenario(), 8))


def test_production_pcm_and_epoch_gate_bounded_repeat_without_browser():
    result = subprocess.run(
        [
            "node",
            str(Path(__file__).with_name("pcm_endurance.cjs")),
            str(ROOT / "app/static/pcm-player.js"),
            str(ROOT / "app/static/app.js"),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=8,
    )
    value = json.loads(result.stdout)
    assert (
        value["passed"]
        and value["cycles"] == 512
        and value["remaining_bytes"] == value["remaining_clips"] == 0
    )
    assert value["retired_peak"] <= 256 and value["pending_timer_peak"] <= 1
    receipt("pcm-endurance.json", value)
