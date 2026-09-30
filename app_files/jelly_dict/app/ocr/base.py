from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


@dataclass(frozen=True)
class OcrToken:
    text: str
    confidence: float = 0.0


@dataclass(frozen=True)
class OcrResult:
    tokens: list[OcrToken]


class OcrProvider(Protocol):
    def extract(self, image_path: Path) -> OcrResult:
        """Return OCR tokens from the image path."""


_WORDISH_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]")
_SPLIT_RE = re.compile(r"[\s\r\n\t]+")
_TRIM_CHARS = " \t\r\n\"'`“”‘’.,;:!?()[]{}<>《》〈〉「」『』、。・·|/\\"


def normalize_ocr_tokens(
    raw_tokens: Iterable[OcrToken | str],
    *,
    limit: int = 40,
) -> list[OcrToken]:
    """Clean OCR text into short clickable word candidates.

    The UI only needs word-level candidates, so punctuation-only chunks,
    empty strings, and duplicates are dropped while English and Japanese
    tokens are preserved.
    """
    normalized: list[OcrToken] = []
    seen: set[str] = set()

    for raw in raw_tokens:
        confidence = raw.confidence if isinstance(raw, OcrToken) else 0.0
        text = raw.text if isinstance(raw, OcrToken) else str(raw)
        for piece in _SPLIT_RE.split(text):
            token = unicodedata.normalize("NFKC", piece).strip(_TRIM_CHARS)
            if not token or not _WORDISH_RE.search(token):
                continue
            key = token.lower() if token.isascii() else token
            if key in seen:
                continue
            seen.add(key)
            normalized.append(OcrToken(token, confidence))
            if len(normalized) >= limit:
                return normalized
    return normalized
