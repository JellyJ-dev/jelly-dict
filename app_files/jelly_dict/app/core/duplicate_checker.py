"""Duplicate detection and merge policies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.models import (
    Example,
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
)
from app.core.utils import utc_now_str

DuplicatePolicy = Literal[
    "keep_existing",
    "update_existing",
    "merge_examples_and_memo",
    "add_as_new",
]


@dataclass
class DuplicateDecision:
    policy: DuplicatePolicy
    apply_for_session: bool = False


def is_duplicate(existing: VocabularyEntry | None, candidate: VocabularyEntry) -> bool:
    if existing is None:
        return False
    return (
        existing.language == candidate.language
        and existing.word_key() == candidate.word_key()
    )


def apply_policy(
    existing: VocabularyEntry,
    candidate: VocabularyEntry,
    policy: DuplicatePolicy,
) -> VocabularyEntry | None:
    """Return the entry to write (or None if existing should be kept).

    Caller is responsible for actually writing the result back to storage.
    """
    if policy == "keep_existing":
        return None
    if policy == "update_existing":
        candidate.id = existing.id or candidate.id
        candidate.created_at = existing.created_at or candidate.created_at
        candidate.updated_at = utc_now_str()
        return candidate
    if policy == "merge_examples_and_memo":
        return _merge(existing, candidate)
    if policy == "add_as_new":
        # Caller should append without dedup. Touch timestamps to current.
        candidate.updated_at = utc_now_str()
        return candidate
    raise ValueError(f"unknown policy: {policy}")


def _merge(existing: VocabularyEntry, candidate: VocabularyEntry) -> VocabularyEntry:
    merged = VocabularyEntry.from_dict(existing.to_dict())
    merged.tags = _union(existing.tags, candidate.tags)
    merged.synonyms = _union(existing.synonyms, candidate.synonyms)
    merged.antonyms = _union(existing.antonyms, candidate.antonyms)

    existing_examples = {(ex.source_text_plain, ex.translation_ko) for ex in existing.examples_flat}
    candidate_examples = collect_examples_flat(candidate)
    merged_examples = list(existing.examples_flat)
    for ex in candidate_examples:
        key = (ex.source_text_plain, ex.translation_ko)
        if key not in existing_examples:
            merged_examples.append(
                Example(
                    source_text=ex.source_text,
                    source_text_plain=ex.source_text_plain,
                    translation_ko=ex.translation_ko,
                    order=len(merged_examples),
                )
            )
            existing_examples.add(key)
    merged.examples_flat = merged_examples

    if candidate.memo and candidate.memo not in (existing.memo or ""):
        if existing.memo:
            merged.memo = f"{existing.memo}\n---\n{candidate.memo}"
        else:
            merged.memo = candidate.memo

    if not merged.meaning_groups and candidate.meaning_groups:
        merged.meaning_groups = candidate.meaning_groups
    if not merged.reading and candidate.reading:
        merged.reading = candidate.reading
    if not merged.pronunciation_audio_url and candidate.pronunciation_audio_url:
        merged.pronunciation_audio_url = candidate.pronunciation_audio_url
    if not merged.source_url and candidate.source_url:
        merged.source_url = candidate.source_url

    merged.meanings_summary = (
        merged.meanings_summary or build_meanings_summary(merged)
    )
    merged.updated_at = utc_now_str()
    return merged


def _union(left: list[str], right: list[str]) -> list[str]:
    result = list(left)
    seen = set(left)
    for item in right:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
