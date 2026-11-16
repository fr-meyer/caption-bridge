"""Readiness poller — checks microphone and API key availability."""

from __future__ import annotations

import asyncio
import logging
import platform

from app.config import AppConfig
from app.state import ReadinessCheck, SessionManager

logger = logging.getLogger(__name__)


def _check_api_key(config: AppConfig) -> ReadinessCheck:
    ready = bool(config.mistral_api_key)
    return ReadinessCheck(
        name="API Key",
        key="api_key",
        ready=ready,
        detail="Ready" if ready else "Not configured",
    )


def _check_mic_available() -> ReadinessCheck:
    """Check whether at least one input device is visible to PortAudio."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        if isinstance(devices, dict):
            has_input = devices.get("max_input_channels", 0) > 0
        else:
            has_input = any(
                d.get("max_input_channels", 0) > 0 for d in devices
            )
    except Exception:
        logger.debug("Microphone availability check failed")
        has_input = False

    return ReadinessCheck(
        name="Microphone Available",
        key="mic_available",
        ready=has_input,
        detail="Ready" if has_input else "No input device found",
    )


def _check_mic_permission() -> ReadinessCheck:
    """Check existing authorization without opening input before Start."""
    if platform.system() != "Darwin":
        return ReadinessCheck(name="Microphone Permission", key="mic_permission", ready=True,
                              detail="Input access is checked when Start opens the microphone")
    from app.audio_devices import microphone_authorization

    try:
        ready = microphone_authorization() == 3
    except Exception:
        ready = False
    return ReadinessCheck(name="Microphone Permission", key="mic_permission", ready=ready,
                          detail="Authorized; input opens on Start" if ready
                          else "Existing microphone permission unavailable")


class ReadinessPoller:
    """Periodically checks readiness prerequisites while the session is idle."""

    def __init__(self, manager: SessionManager, config: AppConfig) -> None:
        self._manager = manager
        self._config = config
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._poll_loop())
            logger.info("ReadinessPoller started")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
            logger.info("ReadinessPoller stopped")

    async def evaluate_now(self) -> None:
        """Run all readiness checks immediately and update the manager."""
        loop = asyncio.get_running_loop()
        api_check = _check_api_key(self._config)
        mic_avail, mic_perm = await asyncio.gather(
            loop.run_in_executor(None, _check_mic_available),
            loop.run_in_executor(None, _check_mic_permission),
        )
        self._manager.set_readiness([api_check, mic_avail, mic_perm])

    run_once = evaluate_now

    async def _poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        interval = self._config.readiness_poll_interval_ms / 1000
        try:
            while True:
                if self._manager.session.status not in (
                    "idle_blocked",
                    "idle_ready",
                ):
                    await asyncio.sleep(interval)
                    continue

                api_check = _check_api_key(self._config)
                mic_avail, mic_perm = await asyncio.gather(
                    loop.run_in_executor(None, _check_mic_available),
                    loop.run_in_executor(None, _check_mic_permission),
                )

                self._manager.set_readiness([api_check, mic_avail, mic_perm])
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
