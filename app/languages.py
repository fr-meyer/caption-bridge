"""Supported target languages for translation."""

from __future__ import annotations

SUPPORTED_TARGET_LANGUAGES: list[dict] = [
    {"code": "en", "label": "English"},
    {"code": "ko", "label": "Korean"},
    {"code": "ja", "label": "Japanese"},
    {"code": "zh-CN", "label": "Chinese (Simplified)"},
    {"code": "zh-TW", "label": "Chinese (Traditional)"},
    {"code": "hi", "label": "Hindi"},
    {"code": "es", "label": "Spanish"},
    {"code": "ar", "label": "Arabic"},
    {"code": "fr", "label": "French"},
    {"code": "pt", "label": "Portuguese"},
    {"code": "ru", "label": "Russian"},
    {"code": "de", "label": "German"},
    {"code": "it", "label": "Italian"},
    {"code": "nl", "label": "Dutch"},
    {"code": "tr", "label": "Turkish"},
    {"code": "vi", "label": "Vietnamese"},
    {"code": "th", "label": "Thai"},
    {"code": "pl", "label": "Polish"},
    {"code": "uk", "label": "Ukrainian"},
    {"code": "sv", "label": "Swedish"},
    {"code": "da", "label": "Danish"},
    {"code": "no", "label": "Norwegian"},
    {"code": "fi", "label": "Finnish"},
    {"code": "cs", "label": "Czech"},
    {"code": "ro", "label": "Romanian"},
    {"code": "hu", "label": "Hungarian"},
    {"code": "el", "label": "Greek"},
    {"code": "he", "label": "Hebrew"},
    {"code": "id", "label": "Indonesian"},
    {"code": "ms", "label": "Malay"},
    {"code": "tl", "label": "Tagalog"},
    {"code": "sw", "label": "Swahili"},
    {"code": "bn", "label": "Bengali"},
    {"code": "ta", "label": "Tamil"},
]

_VALID_CODES: set[str] = {lang["code"] for lang in SUPPORTED_TARGET_LANGUAGES}
_CODE_TO_LABEL: dict[str, str] = {lang["code"]: lang["label"] for lang in SUPPORTED_TARGET_LANGUAGES}


def get_available_target_languages() -> list[dict]:
    return SUPPORTED_TARGET_LANGUAGES


def is_valid_target_language(code: str) -> bool:
    return code in _VALID_CODES


def get_language_label(code: str) -> str:
    return _CODE_TO_LABEL.get(code, code)
