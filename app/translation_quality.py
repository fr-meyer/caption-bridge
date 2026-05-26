"""Deterministic translation quality checks and repair prompt construction."""

from __future__ import annotations

import re
import string
import unicodedata
from typing import NamedTuple

MIN_SOURCE_CHARS_FOR_RATIO_CHECK = 25
MIN_LENGTH_RATIO = 0.25
MAX_LENGTH_RATIO = 4.5
MIN_TARGET_SCRIPT_RATIO = 0.15

LATIN_SCRIPT_LANGUAGES = frozenset(
    {
        "en",
        "es",
        "fr",
        "pt",
        "de",
        "it",
        "nl",
        "tr",
        "vi",
        "pl",
        "sv",
        "da",
        "no",
        "fi",
        "cs",
        "ro",
        "hu",
        "id",
        "ms",
        "tl",
        "sw",
    }
)

_WRAPPER_PHRASES = (
    "caption:",
    "here's the translation:",
    "translation:",
    "here is the translation:",
    "translated text:",
    "output:",
)

_FUNCTION_WORDS_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "the",
            "a",
            "an",
            "is",
            "it",
            "in",
            "of",
            "to",
            "and",
            "or",
            "but",
            "for",
            "on",
            "at",
            "by",
            "with",
            "as",
            "be",
            "was",
            "are",
            "were",
            "has",
            "have",
            "had",
            "do",
            "does",
            "did",
            "not",
            "no",
            "so",
            "if",
            "up",
            "out",
            "its",
            "this",
            "that",
            "from",
        }
    ),
    "es": frozenset(
        {
            "el",
            "la",
            "los",
            "las",
            "un",
            "una",
            "de",
            "del",
            "en",
            "y",
            "o",
            "que",
            "es",
            "son",
            "fue",
            "ser",
            "por",
            "para",
            "con",
            "no",
            "si",
            "al",
            "lo",
            "su",
            "se",
            "le",
            "como",
            "pero",
        }
    ),
    "fr": frozenset(
        {
            "le",
            "la",
            "les",
            "un",
            "une",
            "de",
            "du",
            "des",
            "en",
            "et",
            "ou",
            "que",
            "est",
            "sont",
            "était",
            "être",
            "par",
            "pour",
            "avec",
            "ne",
            "pas",
            "si",
            "au",
            "ce",
            "cette",
            "comme",
            "mais",
            "se",
            "il",
            "elle",
        }
    ),
    "pt": frozenset(
        {
            "o",
            "a",
            "os",
            "as",
            "um",
            "uma",
            "de",
            "do",
            "da",
            "em",
            "e",
            "ou",
            "que",
            "é",
            "são",
            "foi",
            "ser",
            "por",
            "para",
            "com",
            "não",
            "se",
            "ao",
            "como",
            "mas",
        }
    ),
    "de": frozenset(
        {
            "der",
            "die",
            "das",
            "den",
            "dem",
            "des",
            "ein",
            "eine",
            "und",
            "oder",
            "ist",
            "sind",
            "war",
            "zu",
            "in",
            "von",
            "mit",
            "für",
            "auf",
            "nicht",
            "es",
            "sich",
            "als",
            "auch",
            "an",
            "bei",
        }
    ),
    "it": frozenset(
        {
            "il",
            "lo",
            "la",
            "i",
            "gli",
            "le",
            "un",
            "una",
            "di",
            "del",
            "della",
            "in",
            "e",
            "o",
            "che",
            "è",
            "sono",
            "era",
            "essere",
            "per",
            "con",
            "non",
            "si",
            "al",
            "come",
            "ma",
        }
    ),
    "nl": frozenset(
        {
            "de",
            "het",
            "een",
            "en",
            "of",
            "is",
            "zijn",
            "was",
            "in",
            "van",
            "met",
            "voor",
            "op",
            "niet",
            "dat",
            "die",
            "dit",
            "als",
            "ook",
            "aan",
            "bij",
            "te",
            "er",
        }
    ),
    "tr": frozenset(
        {
            "ve",
            "veya",
            "bir",
            "bu",
            "ile",
            "için",
            "de",
            "da",
            "ne",
            "gibi",
            "ama",
            "fakat",
            "çok",
            "daha",
            "en",
            "hiç",
            "mi",
            "mu",
            "mı",
            "mü",
        }
    ),
    "pl": frozenset(
        {
            "i",
            "lub",
            "w",
            "na",
            "do",
            "z",
            "za",
            "od",
            "po",
            "nie",
            "jest",
            "są",
            "był",
            "to",
            "ten",
            "ta",
            "się",
            "co",
            "jak",
            "ale",
            "czy",
            "o",
            "u",
            "ze",
        }
    ),
    "sv": frozenset(
        {
            "och",
            "eller",
            "i",
            "på",
            "av",
            "för",
            "med",
            "till",
            "från",
            "om",
            "inte",
            "är",
            "var",
            "en",
            "ett",
            "den",
            "det",
            "de",
            "som",
            "att",
            "sig",
        }
    ),
    "da": frozenset(
        {
            "og",
            "eller",
            "i",
            "på",
            "af",
            "for",
            "med",
            "til",
            "fra",
            "om",
            "ikke",
            "er",
            "var",
            "en",
            "et",
            "den",
            "det",
            "de",
            "som",
            "at",
            "sig",
        }
    ),
    "no": frozenset(
        {
            "og",
            "eller",
            "i",
            "på",
            "av",
            "for",
            "med",
            "til",
            "fra",
            "om",
            "ikke",
            "er",
            "var",
            "en",
            "et",
            "den",
            "det",
            "de",
            "som",
            "at",
            "seg",
        }
    ),
    "fi": frozenset(
        {
            "ja",
            "tai",
            "on",
            "oli",
            "ovat",
            "ei",
            "se",
            "ne",
            "joka",
            "mutta",
            "kun",
            "koska",
            "myös",
            "kaikki",
            "vielä",
            "jo",
        }
    ),
    "cs": frozenset(
        {
            "a",
            "nebo",
            "v",
            "na",
            "do",
            "z",
            "za",
            "od",
            "po",
            "pro",
            "k",
            "s",
            "je",
            "jsou",
            "byl",
            "to",
            "ten",
            "ta",
            "se",
            "co",
            "jak",
            "ale",
            "že",
            "o",
            "u",
            "i",
        }
    ),
    "ro": frozenset(
        {
            "și",
            "sau",
            "în",
            "pe",
            "de",
            "din",
            "cu",
            "pentru",
            "la",
            "nu",
            "este",
            "sunt",
            "era",
            "un",
            "o",
            "ce",
            "cum",
            "dar",
            "că",
            "se",
        }
    ),
    "hu": frozenset(
        {
            "és",
            "vagy",
            "a",
            "az",
            "egy",
            "van",
            "volt",
            "nem",
            "is",
            "de",
            "hogy",
            "mint",
            "meg",
            "már",
            "még",
            "ez",
            "az",
        }
    ),
    "id": frozenset(
        {
            "dan",
            "atau",
            "di",
            "ke",
            "dari",
            "dengan",
            "untuk",
            "pada",
            "yang",
            "ini",
            "itu",
            "ia",
            "tidak",
            "ada",
            "adalah",
            "juga",
            "bahwa",
            "jika",
            "tapi",
        }
    ),
    "ms": frozenset(
        {
            "dan",
            "atau",
            "di",
            "ke",
            "dari",
            "dengan",
            "untuk",
            "pada",
            "yang",
            "ini",
            "itu",
            "ia",
            "tidak",
            "ada",
            "adalah",
            "juga",
            "bahawa",
            "jika",
            "tetapi",
        }
    ),
    "tl": frozenset(
        {
            "at",
            "o",
            "sa",
            "ng",
            "na",
            "ang",
            "si",
            "ni",
            "para",
            "mula",
            "kung",
            "hindi",
            "ito",
            "iyon",
            "siya",
            "mga",
        }
    ),
    "sw": frozenset(
        {
            "na",
            "au",
            "ya",
            "wa",
            "kwa",
            "ni",
            "si",
            "hii",
            "yake",
            "katika",
            "kutoka",
            "kama",
            "lakini",
            "pia",
        }
    ),
    "vi": frozenset(
        {
            "và",
            "hoặc",
            "là",
            "của",
            "trong",
            "trên",
            "với",
            "cho",
            "từ",
            "đến",
            "không",
            "có",
            "đã",
            "sẽ",
            "này",
            "đó",
            "mà",
            "nhưng",
            "nếu",
            "vì",
        }
    ),
    "ru": frozenset(
        {
            "и",
            "или",
            "в",
            "на",
            "с",
            "по",
            "для",
            "от",
            "до",
            "не",
            "это",
            "что",
            "как",
            "но",
            "он",
            "она",
            "они",
            "мы",
            "вы",
            "я",
            "ты",
            "быть",
            "был",
            "была",
            "были",
            "есть",
        }
    ),
    "uk": frozenset(
        {
            "і",
            "або",
            "в",
            "на",
            "з",
            "по",
            "для",
            "від",
            "до",
            "не",
            "це",
            "що",
            "як",
            "але",
            "він",
            "вона",
            "вони",
            "ми",
            "ви",
            "я",
            "ти",
            "бути",
            "був",
            "була",
            "були",
            "є",
        }
    ),
    "el": frozenset(
        {
            "και",
            "ή",
            "σε",
            "από",
            "με",
            "για",
            "δεν",
            "είναι",
            "ήταν",
            "να",
            "το",
            "τα",
            "η",
            "ο",
            "οι",
            "αυτό",
            "αυτή",
            "που",
            "αλλά",
            "αν",
            "ότι",
        }
    ),
    "he": frozenset(
        {
            "ו",
            "או",
            "של",
            "את",
            "על",
            "אל",
            "עם",
            "מ",
            "ב",
            "לא",
            "הוא",
            "היא",
            "הם",
            "זה",
            "כי",
            "אם",
            "אבל",
            "גם",
            "יש",
            "היה",
        }
    ),
    "ar": frozenset(
        {
            "و",
            "أو",
            "في",
            "على",
            "من",
            "إلى",
            "مع",
            "عن",
            "أن",
            "لا",
            "هو",
            "هي",
            "هم",
            "هذا",
            "هذه",
            "ما",
            "كما",
            "لكن",
            "إذا",
            "كان",
            "يكون",
        }
    ),
    "hi": frozenset(
        {
            "और",
            "या",
            "में",
            "पर",
            "से",
            "को",
            "के",
            "का",
            "की",
            "है",
            "हैं",
            "था",
            "थी",
            "यह",
            "वह",
            "नहीं",
            "भी",
            "जो",
            "कि",
            "लेकिन",
            "अगर",
            "तो",
            "एक",
        }
    ),
    "th": frozenset(
        {
            "และ",
            "หรือ",
            "ใน",
            "ที่",
            "จาก",
            "กับ",
            "เป็น",
            "มี",
            "ได้",
            "จะ",
            "ไม่",
            "นี้",
            "นั้น",
            "แต่",
            "ถ้า",
            "ว่า",
        }
    ),
    "ko": frozenset(
        {
            "이",
            "그",
            "저",
            "것",
            "은",
            "는",
            "가",
            "을",
            "를",
            "의",
            "에",
            "에서",
            "와",
            "과",
            "도",
            "만",
            "로",
            "으로",
            "하다",
            "있다",
            "없다",
            "않",
            "고",
            "면",
            "서",
            "다",
        }
    ),
    "ja": frozenset(
        {
            "は",
            "が",
            "を",
            "に",
            "で",
            "と",
            "も",
            "の",
            "へ",
            "から",
            "まで",
            "より",
            "です",
            "ます",
            "ない",
            "ある",
            "いる",
            "する",
            "した",
            "して",
            "だ",
        }
    ),
    "zh-CN": frozenset(
        {
            "的",
            "了",
            "在",
            "是",
            "我",
            "你",
            "他",
            "她",
            "它",
            "们",
            "这",
            "那",
            "有",
            "没有",
            "不",
            "也",
            "就",
            "都",
            "和",
            "与",
            "或",
            "但",
            "而",
            "因为",
            "所以",
            "如果",
        }
    ),
    "zh-TW": frozenset(
        {
            "的",
            "了",
            "在",
            "是",
            "我",
            "你",
            "他",
            "她",
            "它",
            "們",
            "這",
            "那",
            "有",
            "沒有",
            "不",
            "也",
            "就",
            "都",
            "和",
            "與",
            "或",
            "但",
            "而",
            "因為",
            "所以",
            "如果",
        }
    ),
    "bn": frozenset(
        {
            "এবং",
            "বা",
            "এ",
            "এটি",
            "তার",
            "তা",
            "কে",
            "কি",
            "থেকে",
            "জন্য",
            "দিয়ে",
            "হয়",
            "ছিল",
            "না",
            "নেই",
            "কিন্তু",
            "যদি",
        }
    ),
    "ta": frozenset(
        {
            "மற்றும்",
            "அல்லது",
            "இந்த",
            "அந்த",
            "இது",
            "அது",
            "என்று",
            "உள்ள",
            "மீது",
            "இல்",
            "அல்ல",
            "ஆகும்",
        }
    ),
}

_NUMBERED_LIST_PATTERN = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
_BULLET_PATTERN = re.compile(r"^\s*[-*•]\s", re.MULTILINE)
_INLINE_ALTERNATIVE_PATTERN = re.compile(
    r" or:| alternative:| option ", re.IGNORECASE
)

_NON_LATIN_SCRIPT_PATTERN = re.compile(
    r"[\uAC00-\uD7A3\u1100-\u11FF"  # Hangul
    r"\u4E00-\u9FFF\u3400-\u4DBF"  # CJK
    r"\u3040-\u309F"  # Hiragana
    r"\u30A0-\u30FF"  # Katakana
    r"\u0600-\u06FF"  # Arabic
    r"\u0900-\u097F"  # Devanagari
    r"\u0E00-\u0E7F"  # Thai
    r"\u0590-\u05FF"  # Hebrew
    r"\u0400-\u04FF"  # Cyrillic
    r"\u0370-\u03FF"  # Greek
    r"\u0980-\u09FF"  # Bengali
    r"\u0B80-\u0BFF"  # Tamil
    r"]"
)

_CJK_PATTERN = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF]")
_CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")

_TARGET_SCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "ko": re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF]"),
    "ja": re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]"),
    "zh-CN": _CJK_PATTERN,
    "zh-TW": _CJK_PATTERN,
    "ar": re.compile(r"[\u0600-\u06FF]"),
    "hi": re.compile(r"[\u0900-\u097F]"),
    "bn": re.compile(r"[\u0980-\u09FF]"),
    "th": re.compile(r"[\u0E00-\u0E7F]"),
    "he": re.compile(r"[\u0590-\u05FF]"),
    "ru": _CYRILLIC_PATTERN,
    "uk": _CYRILLIC_PATTERN,
    "el": re.compile(r"[\u0370-\u03FF]"),
    "ta": re.compile(r"[\u0B80-\u0BFF]"),
}

_PUNCTUATION = string.punctuation


def _is_unicode_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P")


class QualityCheckResult(NamedTuple):
    flagged: bool
    reasons: list[str]


def _has_prompt_leakage(text_lower: str) -> bool:
    for phrase in _WRAPPER_PHRASES:
        if text_lower.startswith(phrase) or phrase in text_lower:
            return True
    return False


def _has_multiple_alternatives(text: str) -> bool:
    if _NUMBERED_LIST_PATTERN.search(text):
        return True
    if _BULLET_PATTERN.search(text):
        return True
    if _INLINE_ALTERNATIVE_PATTERN.search(text):
        return True
    return False


def _latin_letter_ratio(text: str) -> float:
    significant = 0
    latin = 0
    for char in text:
        if char.isspace() or _is_unicode_punctuation(char):
            continue
        significant += 1
        if "A" <= char <= "Z" or "a" <= char <= "z":
            latin += 1
    if significant == 0:
        return 0.0
    return latin / significant


def _target_script_ratio(text: str, target_language: str) -> float:
    pattern = _TARGET_SCRIPT_PATTERNS.get(target_language)
    if pattern is None:
        return 0.0
    significant = 0
    target = 0
    for char in text:
        if char.isspace() or _is_unicode_punctuation(char):
            continue
        significant += 1
        if pattern.fullmatch(char):
            target += 1
    if significant == 0:
        return 0.0
    return target / significant


def _has_residual_source_script(
    translated_text: str, source_text: str, target_language: str
) -> bool:
    if target_language in LATIN_SCRIPT_LANGUAGES:
        return _NON_LATIN_SCRIPT_PATTERN.search(translated_text) is not None

    source_stripped = source_text.strip()
    if source_stripped:
        latin_ratio_high = _latin_letter_ratio(translated_text) > 0.7
        if target_language in _TARGET_SCRIPT_PATTERNS:
            target_ratio = _target_script_ratio(translated_text, target_language)
            return latin_ratio_high and target_ratio < MIN_TARGET_SCRIPT_RATIO
        return latin_ratio_high
    return False


def _has_suspicious_length_ratio(translated_text: str, source_text: str) -> bool:
    source_stripped = source_text.strip()
    if len(source_stripped) < MIN_SOURCE_CHARS_FOR_RATIO_CHECK:
        return False
    translated_stripped = translated_text.strip()
    if not translated_stripped:
        return True
    ratio = len(translated_stripped) / len(source_stripped)
    return ratio < MIN_LENGTH_RATIO or ratio > MAX_LENGTH_RATIO


def _is_function_word_only(translated_text: str, target_language: str) -> bool:
    function_words = _FUNCTION_WORDS_BY_LANGUAGE.get(target_language)
    if not function_words:
        return False
    tokens: list[str] = []
    for raw_token in translated_text.split():
        token = raw_token.strip(_PUNCTUATION).lower()
        if token:
            tokens.append(token)
    if not tokens:
        return False
    return all(token in function_words for token in tokens)


def check(
    translated_text: str, source_text: str, target_language: str
) -> QualityCheckResult:
    reasons: list[str] = []
    text_lower = translated_text.strip().lower()

    if _has_prompt_leakage(text_lower):
        reasons.append("prompt_leakage")

    if _has_multiple_alternatives(translated_text):
        reasons.append("multiple_alternatives")

    if _has_residual_source_script(translated_text, source_text, target_language):
        reasons.append("residual_source_script")

    if _has_suspicious_length_ratio(translated_text, source_text):
        reasons.append("length_ratio")

    if _is_function_word_only(translated_text, target_language):
        reasons.append("function_word_only")

    return QualityCheckResult(flagged=len(reasons) > 0, reasons=reasons)


def choose_better_translation(
    raw_text: str,
    repair_text: str,
    source_text: str,
    target_language: str,
) -> str:
    """Return the cleaner of two flagged candidates; prefer the original on a tie."""
    raw_result = check(raw_text, source_text, target_language)
    repair_result = check(repair_text, source_text, target_language)

    if not raw_result.flagged:
        return raw_text
    if not repair_result.flagged:
        return repair_text
    if len(repair_result.reasons) < len(raw_result.reasons):
        return repair_text
    return raw_text


def build_repair_prompt(
    source_text: str, target_language: str, reasons: list[str]
) -> list[dict]:
    problems = ", ".join(reasons)
    system_content = (
        f"Translate the segment into {target_language}. "
        f"Output only the translation with no wrappers, no alternatives, "
        f"no explanations, and no markdown. "
        f"Avoid these detected problems: {problems}."
    )
    user_content = (
        f"Target language: {target_language}\n"
        f"Previous attempt was rejected for: {problems}. "
        f"Provide only the corrected translation.\n\n"
        f"<segment_to_translate>\n{source_text}\n</segment_to_translate>"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
