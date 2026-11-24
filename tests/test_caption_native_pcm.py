"""OFFLINE UNIT ONLY: synthetic PCM and fake workers, never physical acceptance."""
import asyncio
import os
import random
import struct
import sys
from types import SimpleNamespace
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.audio_devices import GrantedNativeInputDevices, NativeInputSelection
from app.native_capture import NativeAudioCapture, NativeCaptureFactory
from app.native_pcm import (ASR_RATE, END, HEADER, MAGIC, MAX_PACKET, AsrPcmConverter,
                            PcmDecoder, PcmProtocolError)
from scripts.attended_native_launch import EmergencyStop, launch_pcm

EPOCH = bytes.fromhex("12" * 16)


def packet(sequence=0, pcm=b"\x01\x00" * 12, rate=16000, channels=1, flags=0, epoch=EPOCH,
           frames=None, size=None, magic=MAGIC):
    frames = len(pcm) // (2 * channels) if frames is None else frames
    size = len(pcm) if size is None else size
    return HEADER.pack(magic, epoch, sequence, rate, channels, flags, frames, size) + pcm


def test_packet_wire_vector_and_random_fragmentation():
    data = packet() + packet(1) + packet(2, pcm=b"", flags=END)
    for seed in range(30):
        decoder = PcmDecoder(EPOCH, 2000)
        rng, chunks, offset = random.Random(seed), [], 0
        while offset < len(data):
            n = rng.randint(1, 57)
            chunks.extend(decoder.feed(data[offset:offset+n]))
            offset += n
        decoder.eof()
        assert chunks == [b"\x01\x00" * 12] * 2
        assert decoder.frames == 24
        assert decoder.format == (16000, 1)
    assert HEADER.size == 48
    assert MAX_PACKET == 496


@pytest.mark.parametrize("override", [
    dict(sequence=1), dict(epoch=bytes(16)), dict(rate=7999), dict(rate=192001),
    dict(channels=3), dict(flags=2), dict(frames=0), dict(size=449), dict(size=22),
    dict(flags=END), dict(magic=b"CBPCM002"), dict(frames=200000),
])
def test_bad_header_fails_before_any_payload_is_admitted(override):
    with pytest.raises(PcmProtocolError):
        PcmDecoder(EPOCH, 2000).feed(packet(**override))


def test_eof_replay_format_duration_and_no_end_are_rejected():
    for raw in (b"", packet()[:-1], packet()):
        decoder = PcmDecoder(EPOCH, 2000)
        decoder.feed(raw)
        with pytest.raises(PcmProtocolError, match="truncated"):
            decoder.eof()
    decoder = PcmDecoder(EPOCH, 1)
    with pytest.raises(PcmProtocolError, match="duration"):
        decoder.feed(packet(pcm=bytes(40)))
    decoder = PcmDecoder(EPOCH, 2000)
    decoder.feed(packet())
    with pytest.raises(PcmProtocolError, match="format_changed"):
        decoder.feed(packet(1, rate=48000))
    decoder = PcmDecoder(EPOCH, 2000)
    decoder.feed(packet(pcm=b"", flags=END))
    with pytest.raises(PcmProtocolError, match="after_end"):
        decoder.feed(packet(1))
    with pytest.raises(PcmProtocolError):
        PcmDecoder(EPOCH, 2000).feed(bytes(4 * MAX_PACKET + 1))


def test_asr_conversion_exact_mono_and_stateful_chunk_independence():
    # Deterministic synthetic unit data. No microphone/source recording.
    stereo = b"".join(struct.pack("<hh", n * 20, n * 40) for n in range(300))
    whole = AsrPcmConverter(ASR_RATE).convert(stereo, (48000, 2))
    converter = AsrPcmConverter(ASR_RATE)
    split = b"".join(converter.convert(stereo[i:i+32], (48000, 2)) for i in range(0, len(stereo), 32))
    assert whole == split
    assert len(whole) == 200  # Exactly 100 mono PCM16 ASR samples.
    assert struct.unpack_from("<h", whole, 2)[0] == 90
    mono = bytes(448)
    assert AsrPcmConverter(ASR_RATE).convert(mono, (16000, 1)) is mono
    with pytest.raises(ValueError, match="asr_contract"):
        AsrPcmConverter(48000)
    with pytest.raises(PcmProtocolError, match="format_changed"):
        converter.convert(bytes(24), (16000, 1))
    converter.clear()
    assert converter.state is None


def make_capture(loop, emergency, *, maximum=8, current=lambda: True, ingress=None):
    expiry = time.time_ns() + 50_000_000_000
    launch = dict(epoch=EPOCH.hex(), milliseconds=2000, expires_unix_ns=expiry,
                  pcm_expires_unix_ns=expiry)
    return NativeAudioCapture(launch, None, None, emergency, sample_rate=16000, loop=loop,
                              max_queue_chunks=maximum, is_current=current,
                              ingress_callback=ingress)


def test_fake_worker_finish_drains_after_clean_end_without_blocking_loop():
    async def scenario():
        loop = asyncio.get_running_loop()
        emergency = EmergencyStop()
        started = threading.Event()
        close_seen = threading.Event()
        ingress = []
        def fake_worker(_launch, _admission, _custody, _emergency, pcm_fd, finish_fd):
            try:
                started.set()
                os.write(pcm_fd, packet())
                assert os.read(finish_fd, 1) == b""  # Real private-pipe finish.
                os.write(pcm_fd, packet(1))
                os.write(pcm_fd, packet(2, pcm=b"", flags=END))
                close_seen.set()
            finally:
                os.close(pcm_fd)
                os.close(finish_fd)
        capture = make_capture(loop, emergency, ingress=ingress.append)
        with patch("app.native_capture.launch_pcm", fake_worker):
            capture.start()
            await asyncio.wait_for(capture.wait_started(), 1)
            assert started.is_set()
            capture.finish_input()
            await asyncio.wait_for(capture.wait_input_finished(), 1)
            chunks = [data async for data in capture.stream()]
            assert chunks == [b"\x01\x00" * 24]
            assert close_seen.is_set()
            assert len(ingress) == 2
            assert capture._read_fd is None and capture._finish_writer is None
            assert capture._queue.empty()
            await capture.aclose()
        emergency.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["queue", "epoch", "sequence", "eof", "worker", "generation", "after_end"])
def test_fake_worker_faults_abort_and_discard_not_fallback_or_normal_eof(failure):
    async def scenario():
        loop = asyncio.get_running_loop()
        emergency = EmergencyStop()
        current = [True]
        def fake_worker(_launch, _admission, _custody, _emergency, pcm_fd, finish_fd):
            try:
                if failure == "worker":
                    raise RuntimeError("PRIVATE-ERROR-DO-NOT-EXPOSE")
                if failure == "generation":
                    current[0] = False
                data = packet()
                if failure == "queue":
                    data = b"".join(packet(n, pcm=bytes(448)) for n in range(16))
                elif failure == "epoch":
                    data = packet(epoch=b"q" * 16)
                elif failure == "sequence":
                    data = packet(sequence=1)
                elif failure == "after_end":
                    data = packet(pcm=b"", flags=END) + packet(1)
                os.write(pcm_fd, data)
            finally:
                os.close(pcm_fd)
                os.close(finish_fd)
        capture = make_capture(loop, emergency, maximum=1, current=lambda: current[0])
        with patch("app.native_capture.launch_pcm", fake_worker):
            capture.start()
            # Wait for owned synthetic worker and pipe callback, not a busy loop.
            if failure != "worker":
                await asyncio.wait_for(asyncio.shield(capture._task), 1)
            await asyncio.sleep(0.02)
            with pytest.raises(PcmProtocolError) as exc:
                _ = [data async for data in capture.stream()]
            assert "PRIVATE" not in str(exc.value)
            if failure == "queue":
                assert "backpressure" in str(exc.value)
            assert capture._queue.empty() and capture._read_fd is None
            assert os.read(emergency.reader, 1) == b""
            await capture.aclose()
        emergency.close()
    asyncio.run(scenario())


def test_stop_discards_fixed_queue_and_joins_worker():
    async def scenario():
        loop = asyncio.get_running_loop()
        emergency = EmergencyStop()
        closed = threading.Event()
        def worker(_a, _b, _c, _d, pcm_fd, finish_fd):
            try:
                os.write(pcm_fd, packet())
                os.read(finish_fd, 1)
            finally:
                os.close(pcm_fd)
                os.close(finish_fd)
                closed.set()
        capture = make_capture(loop, emergency)
        with patch("app.native_capture.launch_pcm", worker):
            capture.start()
            await asyncio.wait_for(capture.wait_started(), 1)
            capture.stop()
            assert capture._queue.empty()
            await capture.aclose()
            assert closed.is_set() and capture._task.done()
            assert [data async for data in capture.stream()] == []
        emergency.close()
    asyncio.run(scenario())


def test_native_catalog_never_queries_portaudio_or_exposes_hal_id():
    catalog = GrantedNativeInputDevices(NativeCaptureFactory())
    with patch.dict(sys.modules, {"sounddevice": SimpleNamespace(
            query_devices=lambda: pytest.fail("PortAudio touched"))}):
        assert "HAL" not in str(catalog.snapshot())
        catalog.choose("default")
        with pytest.raises(ValueError, match="independent proof"):
            catalog.capture_device()
        with pytest.raises(ValueError):
            catalog.choose(0)
        with patch.object(catalog._factory, "preflight"):
            assert type(catalog.capture_device()) is NativeInputSelection
        catalog.reset()
        assert catalog.snapshot()["active_label"] is None


def test_nonmac_launch_failure_closes_owned_fds_without_consumption_or_spawn():
    read_fd, write_fd = os.pipe()
    finish_fd, finish_writer = os.pipe()
    emergency = EmergencyStop()
    try:
        with patch("scripts.attended_native_launch.subprocess.Popen") as spawn:
            with pytest.raises(RuntimeError, match="not_admitted"):
                launch_pcm({}, None, None, emergency, write_fd, finish_fd)
            spawn.assert_not_called()
        for fd in (write_fd, finish_fd):
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        os.close(read_fd)
        os.close(finish_writer)
        emergency.close()


def test_native_source_protocol_paths_stay_separate_and_atomic():
    root = Path(__file__).resolve().parents[1]
    assembly = (root / "native/caption_helper/assembly.c").read_text()
    role = (root / "native/caption_helper/capture_role.c").read_text()
    transport = (root / "native/caption_helper/pcm_transport.h").read_text()
    assert '"capture_pcm_budget_ready"' in assembly and '"CBPC0002"' in assembly
    assert '"CBCA0002"' in assembly and '"CBNC0002"' in assembly
    assert "close_owned(&capture_pcm_fd)" in assembly
    assert "cb_capture_close" in role[:role.index("cb_pcm_packet(10")]
    assert "write(fd,packet,CB_PCM_HEADER+size)" in transport
    assert "fpathconf(fd,_PC_PIPE_BUF)>=512" in transport
    assert "poll(" not in transport and "fwrite" not in transport
    capture = (root / "native/caption_helper/capture_input.c").read_text()
    assert "frames>s->pcm_frame_limit-s->pcm_frames" in capture
