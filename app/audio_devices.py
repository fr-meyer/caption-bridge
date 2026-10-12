"""Transient native microphone choices; never journal or export this metadata."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from threading import RLock
from typing import Any

SELECTION_ERROR = "Microphone selection is unavailable. Refresh devices and choose again."


class InputDevices:
    """Keep native IDs separate from browser output IDs and freeze input on Start."""

    def __init__(self, query: Callable, default: Callable, check: Callable) -> None:
        self._query = query
        self._lock = RLock()
        self._default = default
        self._check = check
        self._choices: dict[str, tuple[int, tuple, str]] = {}
        self._selected = "default"
        self._active: tuple[int, tuple, str] | None = None
        self._unavailable = False

    @staticmethod
    def _identity(device: dict) -> tuple:
        return (device.get("name"), device.get("hostapi"),
                device.get("max_input_channels"), device.get("default_samplerate"))

    def refresh(self) -> dict[str, Any]:
        with self._lock:
            return self._refresh()

    def _refresh(self) -> dict[str, Any]:
        try:
            inventory = self._query()
            previous = {(value[0], value[1]): token for token, value in self._choices.items()}
            choices = {}
            for index, device in enumerate(inventory):
                if device.get("max_input_channels", 0) <= 0:
                    continue
                identity = self._identity(device)
                token = previous.get((index, identity)) or secrets.token_urlsafe(18)
                choices[token] = (index, identity, str(device.get("name", "Microphone"))[:120])
            self._choices = choices
            self._unavailable = False
        except Exception:
            self._choices = {}
            self._unavailable = True
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict[str, Any]:
        return {
            "available": [{"id": token, "label": value[2]}
                          for token, value in self._choices.items()],
            "selected": self._selected,
            "active_label": self._active[2] if self._active else None,
            "unavailable": self._unavailable,
        }

    def choose(self, token: object) -> None:
        with self._lock:
            self._choose(token)

    def _choose(self, token: object) -> None:
        if not isinstance(token, str) or len(token) > 128:
            raise ValueError(SELECTION_ERROR)
        self.refresh()
        if token != "default" and token not in self._choices:
            raise ValueError(SELECTION_ERROR)
        self._selected = token
        self._active = None

    def capture_device(self) -> int:
        """Revalidate immediately before opening; reconnect keeps the original input."""
        with self._lock:
            return self._capture_device()

    def _capture_device(self) -> int:
        self.refresh()
        if self._unavailable:
            raise ValueError(SELECTION_ERROR)
        if self._active is not None:
            selected = self._active
            if not any(value[:2] == selected[:2] for value in self._choices.values()):
                raise ValueError(SELECTION_ERROR)
        elif self._selected == "default":
            try:
                index = self._default()
            except Exception:
                raise ValueError(SELECTION_ERROR) from None
            selected = next((value for value in self._choices.values() if value[0] == index), None)
            if selected is None:
                raise ValueError(SELECTION_ERROR)
        else:
            selected = self._choices.get(self._selected)
            if selected is None:
                raise ValueError(SELECTION_ERROR)
        try:
            self._check(device=selected[0], channels=1, dtype="int16", samplerate=16000)
        except Exception:
            raise ValueError("Selected microphone does not support the required input format.") from None
        self._active = selected
        return selected[0]

    def reset(self) -> None:
        with self._lock:
            self._selected = "default"
            self._active = None


def native_input_devices() -> InputDevices:
    import sounddevice as sd

    return InputDevices(sd.query_devices, lambda: int(sd.default.device[0]), sd.check_input_settings)


def microphone_authorization() -> int:
    """macOS authorization getter only; never requests permission or opens input."""
    import ctypes as c

    av = c.CDLL("/System/Library/Frameworks/AVFoundation.framework/AVFoundation")
    objc = c.CDLL("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes = [c.c_char_p]
    objc.objc_getClass.restype = c.c_void_p
    objc.sel_registerName.argtypes = [c.c_char_p]
    objc.sel_registerName.restype = c.c_void_p
    objc.objc_msgSend.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p]
    objc.objc_msgSend.restype = c.c_long
    media_type = c.c_void_p.in_dll(av, "AVMediaTypeAudio").value
    return objc.objc_msgSend(objc.objc_getClass(b"AVCaptureDevice"),
                             objc.sel_registerName(b"authorizationStatusForMediaType:"), media_type)
