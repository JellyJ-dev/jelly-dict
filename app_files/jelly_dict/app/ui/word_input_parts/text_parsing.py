from __future__ import annotations

import re

BULK_INPUT_SPLIT_RE = re.compile(r"[\r\n,;，；、]+")


def _elide(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _compact_detection_status(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text.replace("감지된 언어:", "감지:")
    return " ".join(text.split())


def split_bulk_input(text: str) -> list[str]:
    """Split explicit separators while preserving phrases with spaces."""
    pieces = [piece.strip() for piece in BULK_INPUT_SPLIT_RE.split(text or "")]
    out: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if not piece:
            continue
        key = piece.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(piece)
    return out
