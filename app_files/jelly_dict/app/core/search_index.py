from __future__ import annotations

import unicodedata

from app.core.models import Example, VocabularyEntry


def normalize_search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


def build_entry_search_blob(entry: VocabularyEntry) -> str:
    parts: list[str] = [
        entry.word,
        entry.reading or "",
        entry.meanings_summary,
        " ".join(entry.tags),
        entry.memo,
        " ".join(entry.synonyms),
        " ".join(entry.antonyms),
    ]
    examples: list[Example] = list(entry.examples_flat)
    for group in entry.meaning_groups:
        parts.append(group.pos)
        for sense in group.senses:
            parts.append(sense.gloss)
            for sub_sense in sense.sub_senses:
                parts.extend(
                    (
                        sub_sense.label,
                        sub_sense.gloss,
                        " ".join(sub_sense.synonyms),
                        " ".join(sub_sense.antonyms),
                    )
                )
                examples.extend(sub_sense.examples)
    parts.extend(_example_text(example) for example in examples)
    return build_search_blob(parts)


def build_search_blob(parts: list[str] | tuple[str, ...]) -> str:
    return normalize_search_text("\n".join(part for part in parts if part))


def search_blob_matches(search_blob: str, query: str) -> bool:
    tokens = normalize_search_text(query).split()
    return not tokens or all(token in search_blob for token in tokens)


def _example_text(example: Example) -> str:
    return " ".join(
        part
        for part in (
            example.source_text_plain,
            example.source_text,
            example.translation_ko or "",
        )
        if part
    )
