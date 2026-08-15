"""Provider error classification for Mistral SDK exceptions."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ProviderErrorInfo:
    provider: str = "mistral"
    status_code: int | None = None
    error_type: str | None = None
    code: str | None = None
    message: str | None = None
    raw: str | None = None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _mistral_fields_from_dict(
    data: dict,
) -> tuple[int | None, str | None, str | None, str | None]:
    return (
        _coerce_int(data.get("raw_status_code")),
        _coerce_str(data.get("type")),
        _coerce_str(data.get("code")),
        _coerce_str(data.get("message")),
    )


def _parse_body_json(body: str | None) -> dict:
    if not body:
        return {}
    try:
        loaded = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parse_embedded_json(text: str) -> dict | None:
    try:
        loaded = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        loaded = None
    if isinstance(loaded, dict):
        return loaded

    brace = text.find("{")
    if brace < 0:
        return None
    try:
        loaded = json.loads(text[brace:])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _is_mistral_error_shape(data: dict) -> bool:
    return any(key in data for key in ("type", "code", "raw_status_code"))


_RECOGNIZED_MISTRAL_ERROR_TYPES = frozenset(
    {"service_tier_capacity_exceeded", "guardrail_violation"}
)


def _is_recognized_mistral_extraction(
    error_type: str | None,
    code: str | None,
    parsed: dict,
) -> bool:
    if error_type in _RECOGNIZED_MISTRAL_ERROR_TYPES:
        return True
    return bool(error_type or code) and _is_mistral_error_shape(parsed)


def extract_provider_error_info(exc: Exception) -> ProviderErrorInfo | None:
    try:
        raw = str(exc)

        status_code = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        exc_message = getattr(exc, "message", None)

        if status_code is not None or body is not None:
            parsed = _parse_body_json(body if isinstance(body, str) else None)
            json_status, error_type, code, json_message = _mistral_fields_from_dict(parsed)
            resolved_status = _coerce_int(status_code)
            if resolved_status is None:
                resolved_status = json_status
            resolved_message = json_message
            if resolved_message is None and isinstance(exc_message, str):
                resolved_message = exc_message
            if (
                resolved_status is not None
                or _is_recognized_mistral_extraction(error_type, code, parsed)
            ):
                return ProviderErrorInfo(
                    provider="mistral",
                    status_code=resolved_status,
                    error_type=error_type,
                    code=code,
                    message=resolved_message,
                    raw=raw,
                )

        embedded = _parse_embedded_json(raw)
        if embedded is not None:
            json_status, error_type, code, message = _mistral_fields_from_dict(embedded)
            if (
                json_status is not None
                or _is_recognized_mistral_extraction(error_type, code, embedded)
            ):
                return ProviderErrorInfo(
                    provider="mistral",
                    status_code=json_status,
                    error_type=error_type,
                    code=code,
                    message=message,
                    raw=raw,
                )

        if "service_tier_capacity_exceeded" in raw:
            return ProviderErrorInfo(
                provider="mistral",
                status_code=429,
                error_type="service_tier_capacity_exceeded",
                raw=raw,
            )
        if "guardrail_violation" in raw:
            return ProviderErrorInfo(
                provider="mistral",
                status_code=403,
                error_type="guardrail_violation",
                raw=raw,
            )

        return None
    except Exception:
        return None


def is_capacity_exceeded(info: ProviderErrorInfo | None) -> bool:
    return (
        info is not None
        and info.status_code == 429
        and info.error_type == "service_tier_capacity_exceeded"
    )


def is_transient_provider_error(info: ProviderErrorInfo | None) -> bool:
    return (
        info is not None
        and info.status_code in {408, 429, 500, 502, 503, 504}
    )


def is_tts_guardrail_violation(info: ProviderErrorInfo | None) -> bool:
    return (
        info is not None
        and info.status_code == 403
        and info.error_type == "guardrail_violation"
    )
