from __future__ import annotations

from copy import deepcopy

from app.core.meaning_display import replace_nested_examples
from app.core.models import VocabularyEntry, build_meanings_summary


class EntryProjectionService:
    """Build the saved-entry read model with Excel as the authority."""

    def project_saved(
        self,
        excel_entry: VocabularyEntry,
        cached: VocabularyEntry | None,
    ) -> VocabularyEntry:
        projected = VocabularyEntry.from_dict(excel_entry.to_dict())
        projected.source_provider = "excel"
        if cached is None or not _cache_structure_matches(projected, cached):
            return projected

        if cached.meaning_groups:
            projected.meaning_groups = deepcopy(cached.meaning_groups)
            if projected.examples_flat:
                replace_nested_examples(
                    projected.meaning_groups,
                    projected.examples_flat,
                )
        if not projected.examples_flat and cached.examples_flat:
            projected.examples_flat = deepcopy(cached.examples_flat)
        projected.pronunciation_audio_url = cached.pronunciation_audio_url
        if projected.source_url == cached.source_url:
            projected.source_provider = cached.source_provider
        return projected


def _cache_structure_matches(
    excel_entry: VocabularyEntry,
    cached: VocabularyEntry,
) -> bool:
    if excel_entry.language != cached.language:
        return False
    if excel_entry.word_key() != cached.word_key():
        return False
    excel_summary = excel_entry.meanings_summary or build_meanings_summary(excel_entry)
    cached_summary = cached.meanings_summary or build_meanings_summary(cached)
    return excel_summary.strip() == cached_summary.strip()
