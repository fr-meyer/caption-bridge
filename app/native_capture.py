"""Opt-in native capture factory, with no environment/UI auto-admission or fallback.

The independent coordinator retains the locked programme custody and EmergencyStop.
A factory is one-use and bound to an already authenticated session/generation grant.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from app.native_pcm import MAX_PACKET, AsrPcmConverter, PcmDecoder, PcmProtocolError
from app.pipeline_diagnostics import pcm16_metrics
from scripts.attended_native_launch import EmergencyStop, launch_pcm
from scripts.attended_pcm_admission import PcmAdmission


class NativeCaptureFactory:
    def __init__(self, admission=None, permit=None, custody=None, emergency=None):
        self.admission = admission
        self.permit = permit
        self.custody = custody
        self.emergency = emergency
        self._used = False

    def preflight(self):
        if (self._used or type(self.admission) is not PcmAdmission
                or self.permit is None or self.custody is None
                or type(self.emergency) is not EmergencyStop):
            raise RuntimeError("native_pcm_not_admitted")
        self.emergency.ready()

    def create(self, *, session_id, generation, sample_rate, loop, is_current, **kwargs):
        if (self._used or type(self.admission) is not PcmAdmission
                or self.permit is None or self.custody is None
                or type(self.emergency) is not EmergencyStop):
            raise RuntimeError("native_pcm_not_admitted")
        if sys.platform != "darwin":
            raise RuntimeError("macos_native_only")
        self.preflight()
        self._used = True
        launch = self.admission.consume(self.permit, self.custody, session_id=session_id,
                                        generation=generation, sample_rate=sample_rate,
                                        consumer="app-asr")
        return NativeAudioCapture(launch, self.admission, self.custody, self.emergency,
                                  sample_rate=sample_rate, loop=loop, is_current=is_current, **kwargs)


class NativeAudioCapture:
    """Bounded event-loop ingress, never unbounded thread-safe callback handles.

    Normal finish drains only the fixed queue/pipe tail. Abort, overflow, malformed
    data and generation replacement discard pending PCM and close emergency stop.
    END + clean owned process exit is transport evidence only, never ledger release.
    """

    def __init__(self, launch, admission, custody, emergency, *, sample_rate, loop,
                 is_current, max_queue_chunks=50, metrics_callback=None,
                 onset_callback=None, ingress_callback=None):
        if type(max_queue_chunks) is not int or not 1 <= max_queue_chunks <= 50:
            raise ValueError("native_pcm_queue_bound")
        self._launch = launch
        self._admission = admission
        self._custody = custody
        self._emergency = emergency
        self._loop = loop
        self._is_current = is_current
        self._queue = asyncio.Queue(maxsize=max_queue_chunks)
        self._asr_pending = bytearray()
        self._decoder = PcmDecoder(bytes.fromhex(launch["epoch"]), launch["milliseconds"])
        self._converter = AsrPcmConverter(sample_rate)
        self._metrics_callback = metrics_callback
        self._onset_callback = onset_callback
        self._ingress_callback = ingress_callback
        self._changed = asyncio.Event()
        self._first_pcm = asyncio.Event()
        self._finished = False
        self._error = None
        self._stopped = False
        self._finishing = False
        self._read_fd = None
        self._finish_writer = None
        self._task = None
        self._pipe_eof = False
        self._worker_ok = False
        self._stream_claimed = False

    def start(self):
        if self._task is not None or self._stopped or not self._is_current():
            raise RuntimeError("native_pcm_capture_not_current")
        if time.time_ns() + self._launch["milliseconds"] * 1_000_000 >= min(
                self._launch["expires_unix_ns"], self._launch["pcm_expires_unix_ns"]):
            raise RuntimeError("native_pcm_runtime_expired")
        read_fd, write_fd = os.pipe()
        try:
            finish_fd, finish_writer = os.pipe()
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            raise
        try:
            os.set_blocking(read_fd, False)
            os.set_blocking(write_fd, False)
            self._read_fd, self._finish_writer = read_fd, finish_writer
            self._loop.add_reader(read_fd, self._read_ready)
            self._task = self._loop.create_task(asyncio.to_thread(
                launch_pcm, self._launch, self._admission, self._custody, self._emergency,
                write_fd, finish_fd))
            self._task.add_done_callback(self._worker_done)
        except BaseException:
            self._loop.remove_reader(read_fd)
            for fd in (read_fd, write_fd, finish_fd, finish_writer):
                os.close(fd)
            self._read_fd = self._finish_writer = None
            raise

    async def wait_started(self):
        # Do not start the provider pipeline on an unverified ACK: require actual
        # valid PCM from this epoch. This is not physical/source admission proof.
        while not self._first_pcm.is_set():
            if self._finished:
                raise self._error or PcmProtocolError("native_pcm_no_input")
            self._changed.clear()
            await self._changed.wait()
        if self._error:
            raise self._error

    def _close_reader(self):
        if self._read_fd is not None:
            self._loop.remove_reader(self._read_fd)
            os.close(self._read_fd)
            self._read_fd = None

    def _finish_signal(self):
        if self._finish_writer is not None:
            os.close(self._finish_writer)
            self._finish_writer = None

    def _clear(self):
        while not self._queue.empty():
            self._queue.get_nowait()
        self._asr_pending.clear()
        self._decoder.clear()
        self._converter.clear()

    def _fail(self, reason):
        self._error = PcmProtocolError(reason)
        self.stop()

    def _enqueue_asr(self, chunk):
        if self._queue.full():
            self._fail("native_pcm_backpressure_hold")
            return False
        self._queue.put_nowait(chunk)
        if self._metrics_callback:
            self._metrics_callback(self._queue.qsize(), 0)
        self._changed.set()
        return True

    def _read_ready(self):
        if self._stopped:
            return
        if not self._is_current():
            self._fail("native_pcm_generation_replaced")
            return
        try:
            data = os.read(self._read_fd, 4 * MAX_PACKET)
            if not data:
                self._decoder.eof()
                self._pipe_eof = True
                self._close_reader()
                self._maybe_finished()
                return
            for raw in self._decoder.feed(data):
                chunk = self._converter.convert(raw, self._decoder.format)
                if not chunk:
                    continue
                if self._ingress_callback:
                    self._ingress_callback(pcm16_metrics(chunk, len(chunk) // 2))
                if self._onset_callback:
                    self._onset_callback(chunk)
                # Match the existing 100 ms mono ASR block contract. This avoids
                # treating tiny atomic pipe packets as full application chunks.
                # Pending <3200 + maximum converted packet (<896 bytes).
                self._asr_pending.extend(chunk)
                while len(self._asr_pending) >= 3200:
                    block = bytes(self._asr_pending[:3200])
                    del self._asr_pending[:3200]
                    if not self._enqueue_asr(block):
                        return
                self._first_pcm.set()
                self._changed.set()
            if self._decoder.ended and self._asr_pending:
                tail = bytes(self._asr_pending)
                self._asr_pending.clear()
                self._enqueue_asr(tail)
        except BlockingIOError:
            return
        except Exception:
            # Do not propagate OS paths, payloads or callback exception messages.
            self._fail("native_pcm_ingress_failed_hold")

    def _worker_done(self, task):
        try:
            task.result()
            self._worker_ok = True
        except BaseException:
            if not self._stopped:
                self._fail("native_pcm_terminal_unknown_hold")
        self._maybe_finished()

    def _maybe_finished(self):
        if self._worker_ok and self._pipe_eof:
            self._finished = True
            self._finish_signal()
            self._converter.clear()
            self._changed.set()

    async def stream(self):
        if self._stream_claimed:
            raise RuntimeError("native_pcm_single_consumer")
        self._stream_claimed = True
        while True:
            if not self._is_current():
                self._fail("native_pcm_generation_replaced")
            if self._error:
                raise self._error
            if not self._queue.empty():
                yield self._queue.get_nowait()
            elif self._finished:
                return
            else:
                self._changed.clear()
                await self._changed.wait()

    def finish_input(self):
        if self._stopped or self._finishing:
            return
        self._finishing = True
        self._finish_signal()  # Cooperative native close, not emergency SIGKILL.

    async def wait_input_finished(self):
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 14)
            except asyncio.TimeoutError:
                self._fail("native_pcm_owned_process_pending_hold")
                raise self._error from None
            except Exception:
                self._fail("native_pcm_terminal_unknown_hold")
                raise self._error from None
        while not self._finished:
            self._changed.clear()
            await self._changed.wait()
        if self._error:
            raise self._error

    def stop(self):
        self._stopped = True
        self._emergency.stop()
        self._finish_signal()
        self._close_reader()
        self._clear()
        self._finished = True
        self._changed.set()

    async def aclose(self):
        self.stop()
        if self._task is not None:
            # _run retains/reaps its own controller; never abandon the worker on
            # cancellation. A timeout remains HOLD and an explicitly live task.
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 14)
            except asyncio.TimeoutError:
                raise PcmProtocolError("native_pcm_owned_process_pending_hold") from None
            except Exception:
                # Worker has completed its finally/reap path. Still HOLD, never
                # independent physical closure. Normal emergency Stop is terminal.
                self._error = PcmProtocolError("native_pcm_terminal_unknown_hold")
