"""Display-model helpers for the inline wordbook.

The view accepts legacy 4-tuples for compatibility, but normalizes them
into this richer DTO so metadata can power search without adding visible
UI chrome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from app.core.diagnostics import diagnostic_operation
from app.core.search_index import (
    build_search_blob,
    normalize_search_text,
    search_blob_matches,
)


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
    entry_ref: object | None = field(default=None, compare=False, repr=False)
    search_blob: str = field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        blob = self.search_blob
        if not blob:
            blob = build_search_blob(
                (
                    self.word,
                    self.reading,
                    self.hint,
                    " ".join(self.tags),
                    self.memo,
                    " ".join(self.examples),
                )
            )
        object.__setattr__(self, "search_blob", normalize_search_text(blob))


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
    with diagnostic_operation("workbook_search") as diagnostic:
        matched = [item for item in items if search_blob_matches(item.search_blob, query)]
        diagnostic.finish("empty" if not matched else "success", row_count=len(matched))
        return matched
