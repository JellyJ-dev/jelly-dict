from __future__ import annotations

import unicodedata
from typing import Literal

DetectionResult = Literal["en", "ja", "ambiguous", "unsupported"]


def _is_hiragana(ch: str) -> bool:
    return "぀" <= ch <= "ゟ"


def _is_katakana(ch: str) -> bool:
    return "゠" <= ch <= "ヿ" or "ㇰ" <= ch <= "ㇿ"


def _is_cjk_ideograph(ch: str) -> bool:
    # CJK Unified Ideographs + extension A + compatibility ideographs
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or "豈" <= ch <= "﫿"


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ" or "㄰" <= ch <= "㆏"


def _is_latin_letter(ch: str) -> bool:
    return "a" <= ch.lower() <= "z"


def detect_language(text: str) -> DetectionResult:
    """Detect input language for the vocabulary lookup.

    Stable detection rules:
      - alphabet only -> "en"
      - any hiragana/katakana -> "ja"
      - kanji only -> "ja"
      - en + ja mixed -> "ambiguous"
      - hangul or anything else -> "unsupported"
    """
    if text is None:
        return "unsupported"
    stripped = unicodedata.normalize("NFKC", text).strip()
    if not stripped:
        return "unsupported"

    has_hangul = False
    has_kana = False
    has_kanji = False
    has_latin = False
    has_other_letter = False

    for ch in stripped:
        if ch.isspace() or not ch.isprintable():
            continue
        if _is_hangul(ch):
            has_hangul = True
        elif _is_hiragana(ch) or _is_katakana(ch):
            has_kana = True
        elif _is_cjk_ideograph(ch):
            has_kanji = True
        elif _is_latin_letter(ch):
            has_latin = True
        elif ch.isalpha():
            has_other_letter = True

    if has_hangul:
        return "unsupported"
    if has_other_letter and not (has_kana or has_kanji or has_latin):
        return "unsupported"

    if has_kana:
        # kana wins even if latin chars are mixed in (e.g. loanword + ascii)
        if has_latin:
            return "ambiguous"
        return "ja"
    if has_latin and has_kanji:
        return "ambiguous"
    if has_kanji:
        return "ja"
    if has_latin:
        return "en"
    return "unsupported"
