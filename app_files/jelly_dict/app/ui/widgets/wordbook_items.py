"""Display-model helpers for the inline wordbook.

The view accepts legacy 4-tuples for compatibility, but normalizes them
into this richer DTO so metadata can power search without adding visible
UI chrome.
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
