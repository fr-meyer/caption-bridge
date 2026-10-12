"""Content-free capture and ASR aggregates with an exact persistence schema."""

from __future__ import annotations

import math
import sys
from array import array
from dataclasses import asdict, dataclass, field
from typing import Any

ASR_STATES = frozenset({"idle", "connecting", "ready", "draining", "failed", "stopped"})
ASR_REASONS_V5 = frozenset({
    "none", "initial_timeout", "provider_error", "transport_error", "send_failed",
    "closed_before_ready", "stream_done", "microphone_error", "user_stop", "invalid_audio", "input_finished",
})
ASR_REASONS = ASR_REASONS_V5 | {"settings_mismatch", "closed_before_done"}
ASR_EVENT_TYPES = frozenset({
    "session_created", "session_updated", "text_delta", "done", "provider_error", "unknown", "other",
})
_CAPTURE_KEYS = frozenset({
    "active", "chunks", "bytes", "samples", "frames", "invalid_chunks", "rms", "peak",
})
_ASR_KEYS = frozenset({
    "state", "reason", "handshake_attempts", "handshakes", "sent_frames", "sent_bytes",
    "events", "text_events", "text_characters", "errors", "event_types",
})


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class AsrProtocolDiagnostics:
    """Latest connection's requested/acknowledged settings and terminal facts."""

    requested_sample_rate: int | None = None
    requested_pcm_s16le: bool | None = None
    requested_target_delay_ms: int | None = None
    ack_sample_rate: int | None = None
    ack_pcm_s16le: bool | None = None
    ack_model_matches: bool | None = None
    ack_target_delay_ms: int | None = None
    session_updated_received: bool = False
    settings_verified: bool = False
    delay_verified: bool = False
    input_flushed: bool = False
    input_ended: bool = False
    done_received: bool = False
    done_text_characters: int | None = None
    done_text_handling: str = "not_received"
    prompt_audio_seconds: int | None = None

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


def validate_protocol_snapshot(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != set(AsrProtocolDiagnostics().snapshot()):
        return False
    nullable_counts = {"requested_sample_rate", "requested_target_delay_ms", "ack_sample_rate",
                       "ack_target_delay_ms", "done_text_characters", "prompt_audio_seconds"}
    nullable_bools = {"requested_pcm_s16le", "ack_pcm_s16le", "ack_model_matches"}
    flags = {"session_updated_received", "settings_verified", "delay_verified", "input_flushed",
             "input_ended", "done_received"}
    if any(v is not None and (not _count(v) or v > 2**63 - 1) for v in (value[k] for k in nullable_counts)):
        return False
    if any(value[k] is not None and not isinstance(value[k], bool) for k in nullable_bools):
        return False
    if any(not isinstance(value[k], bool) for k in flags):
        return False
    if any(value[k] is not None and value[k] == 0 for k in {"requested_sample_rate", "ack_sample_rate"}):
        return False
    requested = [value[k] for k in {"requested_sample_rate", "requested_pcm_s16le", "requested_target_delay_ms"}]
    if not (all(v is None for v in requested) or all(v is not None for v in requested)):
        return False
    handling = value["done_text_handling"]
    if not isinstance(handling, str) or handling not in {"not_received", "empty", "final_only_admitted", "deltas_preserved", "not_admitted"}:
        return False
    if value["settings_verified"] and not (
        value["session_updated_received"] and value["ack_model_matches"] is True
        and value["ack_pcm_s16le"] is True and value["requested_pcm_s16le"] is True
        and value["ack_sample_rate"] is not None
        and value["ack_sample_rate"] == value["requested_sample_rate"]
        and (value["ack_target_delay_ms"] is None
             or value["ack_target_delay_ms"] == value["requested_target_delay_ms"])
    ):
        return False
    if not value["session_updated_received"] and any(value[k] is not None for k in {
        "ack_sample_rate", "ack_pcm_s16le", "ack_model_matches", "ack_target_delay_ms"
    }):
        return False
    if value["session_updated_received"] and (
        value["requested_sample_rate"] is None or value["ack_pcm_s16le"] is None
        or value["ack_model_matches"] is None
    ):
        return False
    if value["delay_verified"] and not (
        value["settings_verified"] and value["ack_target_delay_ms"] is not None
        and value["ack_target_delay_ms"] == value["requested_target_delay_ms"]
    ):
        return False
    if value["settings_verified"] and value["delay_verified"] != (value["ack_target_delay_ms"] is not None):
        return False
    if value["input_ended"] and not value["input_flushed"]:
        return False
    if (value["input_flushed"] or handling in {"final_only_admitted", "deltas_preserved"}) and not value["settings_verified"]:
        return False
    if not value["done_received"]:
        return value["done_text_characters"] is None and handling == "not_received" and value["prompt_audio_seconds"] is None
    if value["done_text_characters"] is None or handling == "not_received":
        return False
    return ((handling == "empty") == (value["done_text_characters"] == 0))


def pcm16_metrics(chunk: bytes, frames: int | None = None) -> dict[str, int]:
    """Reduce mono s16le PCM immediately; no sample values survive the call."""
    if not isinstance(chunk, bytes):
        raise ValueError("invalid PCM type")
    samples = len(chunk) // 2
    if frames is None:
        frames = samples
    if not _count(frames):
        raise ValueError("invalid frame count")
    invalid = bool(len(chunk) % 2 or frames != samples)
    values = array("h")
    values.frombytes(chunk[:samples * 2])
    if sys.byteorder != "little":
        values.byteswap()
    return {
        "bytes": len(chunk), "samples": samples, "frames": frames,
        "sum_squares": sum(value * value for value in values),
        "peak": max((abs(value) for value in values), default=0),
        "invalid_chunks": int(invalid),
    }


@dataclass
class PipelineDiagnostics:
    protocol: AsrProtocolDiagnostics = field(default_factory=AsrProtocolDiagnostics)
    capture_active: bool = False
    capture_chunks: int = 0
    capture_bytes: int = 0
    capture_samples: int = 0
    capture_frames: int = 0
    capture_invalid_chunks: int = 0
    _sum_squares: int = 0
    _peak: int = 0
    state: str = "idle"
    reason: str = "none"
    handshake_attempts: int = 0
    handshakes: int = 0
    sent_frames: int = 0
    sent_bytes: int = 0
    events: int = 0
    text_events: int = 0
    text_characters: int = 0
    errors: int = 0
    event_types: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(sorted(ASR_EVENT_TYPES), 0)
    )

    def set_state(self, state: str, reason: str = "none") -> None:
        if not isinstance(state, str) or not isinstance(reason, str) or state not in ASR_STATES or reason not in ASR_REASONS:
            raise ValueError("invalid ASR state or reason")
        self.state, self.reason = state, reason
        if state == "connecting":
            self.handshake_attempts += 1
        elif state == "ready":
            self.handshakes += 1

    def record_capture(self, metrics: dict[str, int]) -> None:
        keys = {"bytes", "samples", "frames", "sum_squares", "peak", "invalid_chunks"}
        if not isinstance(metrics, dict) or set(metrics) != keys or not all(_count(v) for v in metrics.values()):
            raise ValueError("invalid capture metrics")
        if (metrics["peak"] > 32768 or metrics["invalid_chunks"] > 1
                or metrics["samples"] != metrics["bytes"] // 2
                or metrics["sum_squares"] > metrics["samples"] * 32768**2):
            raise ValueError("invalid capture metrics")
        self.capture_chunks += 1
        self.capture_bytes += metrics["bytes"]
        self.capture_samples += metrics["samples"]
        self.capture_frames += metrics["frames"]
        self.capture_invalid_chunks += metrics["invalid_chunks"]
        self._sum_squares += metrics["sum_squares"]
        self._peak = max(self._peak, metrics["peak"])

    def record_sent(self, byte_count: int) -> None:
        if not _count(byte_count) or byte_count % 2:
            raise ValueError("invalid sent PCM length")
        self.sent_bytes += byte_count
        self.sent_frames += 1

    def record_event(self, event_type: str, characters: int = 0) -> None:
        if not isinstance(event_type, str) or event_type not in ASR_EVENT_TYPES or not _count(characters):
            raise ValueError("invalid ASR event metrics")
        self.events += 1
        self.event_types[event_type] += 1
        if event_type == "text_delta":
            self.text_events += 1
            self.text_characters += characters

    def record_error(self) -> None:
        self.errors += 1

    def snapshot(self) -> dict[str, Any]:
        rms = math.sqrt(self._sum_squares / self.capture_samples) / 32768 if self.capture_samples else None
        return {
            "protocol": self.protocol.snapshot(),
            "capture": {
                "active": self.capture_active, "chunks": self.capture_chunks,
                "bytes": self.capture_bytes, "samples": self.capture_samples,
                "frames": self.capture_frames, "invalid_chunks": self.capture_invalid_chunks,
                "rms": round(rms, 6) if rms is not None else None,
                "peak": round(self._peak / 32768, 6) if self.capture_samples else None,
            },
            "asr": {
                "state": self.state, "reason": self.reason,
                "handshake_attempts": self.handshake_attempts, "handshakes": self.handshakes,
                "sent_frames": self.sent_frames, "sent_bytes": self.sent_bytes,
                "events": self.events, "text_events": self.text_events,
                "text_characters": self.text_characters, "errors": self.errors,
                "event_types": dict(self.event_types),
            },
        }


def validate_pipeline_snapshot(value: object, *, legacy_v5: bool = False) -> bool:
    keys = {"capture", "asr"} if legacy_v5 else {"capture", "asr", "protocol"}
    if not isinstance(value, dict) or set(value) != keys:
        return False
    if not legacy_v5 and not validate_protocol_snapshot(value["protocol"]):
        return False
    capture, asr = value["capture"], value["asr"]
    if (not isinstance(capture, dict) or set(capture) != _CAPTURE_KEYS
            or not isinstance(asr, dict) or set(asr) != _ASR_KEYS):
        return False
    if not isinstance(capture["active"], bool):
        return False
    if not all(_count(capture[key]) for key in _CAPTURE_KEYS - {"active", "rms", "peak"}):
        return False
    for key in ("rms", "peak"):
        number = capture[key]
        if capture["samples"] == 0:
            if number is not None:
                return False
            continue
        if (not isinstance(number, (int, float)) or isinstance(number, bool)
                or not 0 <= number <= 1 or not math.isfinite(number)):
            return False
    if (not isinstance(asr["state"], str) or not isinstance(asr["reason"], str)
            or asr["state"] not in ASR_STATES
            or asr["reason"] not in (ASR_REASONS_V5 if legacy_v5 else ASR_REASONS)):
        return False
    if not all(_count(asr[key]) for key in _ASR_KEYS - {"state", "reason", "event_types"}):
        return False
    types = asr["event_types"]
    return (
        isinstance(types, dict) and set(types) == ASR_EVENT_TYPES
        and all(_count(v) for v in types.values())
        and sum(types.values()) == asr["events"]
        and types["text_delta"] == asr["text_events"]
        and asr["sent_bytes"] % 2 == 0
    )
