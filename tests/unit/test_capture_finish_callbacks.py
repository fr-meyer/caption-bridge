"""Native callbacks are faked; no audio device or provider is opened."""
import asyncio

from app.audio import AudioCapture


def test_finish_input_keeps_callback_waiting_for_the_event_loop():
    async def scenario():
        metrics = []
        capture = AudioCapture(16000, asyncio.get_running_loop(), ingress_callback=metrics.append)
        expected = b"\x01\x00" * 1600
        capture._audio_callback(expected, 1600, {}, False)
        capture.finish_input()
        capture._audio_callback(b"\x02\x00" * 1600, 1600, {}, False)
        assert [chunk async for chunk in capture.stream()] == [expected]
        assert len(metrics) == 1 and metrics[0]["bytes"] == len(expected)
        assert capture._queue.empty()
        capture.stop()
    asyncio.run(scenario())


def test_full_queue_preserves_pending_callback_order_without_dropping_old_pcm():
    async def scenario():
        drops = []
        capture = AudioCapture(16000, asyncio.get_running_loop(), max_queue_chunks=1,
                               metrics_callback=lambda _depth, dropped: drops.append(dropped))
        expected = [b"\x01\x00", b"\x02\x00", b"\x03\x00"]
        capture._enqueue_chunk(expected[0])
        for chunk in expected[1:]:
            capture._audio_callback(chunk, 1, {}, False)
        capture.finish_input()
        assert [chunk async for chunk in capture.stream()] == expected
        assert not any(drops)
        capture.stop()
    asyncio.run(scenario())


def test_stop_cancels_eof_barrier_and_discards_pending_callback():
    async def scenario():
        capture = AudioCapture(16000, asyncio.get_running_loop())
        capture._audio_callback(b"\x01\x00", 1, {}, False)
        capture.finish_input()
        capture.stop()
        await asyncio.sleep(0)
        assert [chunk async for chunk in capture.stream()] == []
        assert capture._input_eof_handle is None and capture._sentinel_task is None
        assert capture._final_chunks == []
    asyncio.run(scenario())


def test_stop_interrupts_final_callback_waiting_behind_a_full_queue():
    async def scenario():
        capture = AudioCapture(16000, asyncio.get_running_loop(), max_queue_chunks=1)
        capture._enqueue_chunk(b"\x01\x00")
        capture._audio_callback(b"\x02\x00", 1, {}, False)
        capture.finish_input()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        pending = capture._sentinel_task
        assert pending is not None and not pending.done()
        capture.stop()
        await asyncio.sleep(0)
        assert pending.cancelled()
        assert [chunk async for chunk in capture.stream()] == []
    asyncio.run(scenario())
