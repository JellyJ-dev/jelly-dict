"""Display-model helpers for the inline wordbook.

The view accepts legacy 4-tuples for compatibility, but normalizes them
into this richer DTO so metadata can power search and tooltips without
adding visible UI chrome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias


@dataclass(frozen=True)
class WordbookDisplayItem:
    word: str
    language: str
    reading: str = ""
    hint: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    memo: str = ""
    examples: tuple[str, ...] = field(default_factory=tuple)
    updated_at: str = ""


LegacyWordbookItem: TypeAlias = tuple[str, str, str, str]
WordbookItem: TypeAlias = WordbookDisplayItem | LegacyWordbookItem


def coerce_wordbook_item(item: WordbookItem) -> WordbookDisplayItem:
    if isinstance(item, WordbookDisplayItem):
        return item
    word, language, reading, hint = item
    return WordbookDisplayItem(
        word=str(word or ""),
        language=str(language or ""),
        reading=str(reading or ""),
        hint=str(hint or ""),
    )


def filter_wordbook_items(
    items: list[WordbookDisplayItem],
    query: str,
) -> list[WordbookDisplayItem]:
    tokens = [token.casefold() for token in query.split() if token.strip()]
    if not tokens:
        return list(items)
    return [
        item
        for item in items
        if all(token in _search_text(item) for token in tokens)
    ]


def wordbook_tooltip(item: WordbookDisplayItem) -> str:
    lines = [item.word]
    if item.language == "ja" and item.reading:
        lines.append(item.reading)
    if item.hint:
        lines.append(item.hint)

    meta_lines: list[str] = []
    if item.tags:
        meta_lines.append(f"태그: {', '.join(item.tags[:5])}")
    if item.memo.strip():
        meta_lines.append(f"메모: {_compact_line(item.memo, 90)}")
    if item.examples:
        meta_lines.append(
            f"예문 {len(item.examples)}개: {_compact_line(item.examples[0], 90)}"
        )
    if item.updated_at:
        meta_lines.append(f"수정: {item.updated_at[:10]}")
    if meta_lines:
        lines.append("")
        lines.extend(meta_lines)
    return "\n".join(line for line in lines if line).strip()


def _search_text(item: WordbookDisplayItem) -> str:
    return "\n".join(
        [
            item.word,
            item.reading,
            item.hint,
            " ".join(item.tags),
            item.memo,
            " ".join(item.examples),
        ]
    ).casefold()


def _compact_line(text: str, limit: int) -> str:
    line = " ".join((text or "").split())
    if len(line) <= limit:
        return line
    return line[: limit - 1] + "…"
