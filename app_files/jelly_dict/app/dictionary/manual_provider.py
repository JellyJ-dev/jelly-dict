from __future__ import annotations

from app.core.models import Language, VocabularyEntry
from app.dictionary.base import DictionaryProvider, LookupResult


class ManualDictionaryProvider(DictionaryProvider):
    """Returns a blank entry so the user can fill it in by hand.

    Used as a fallback when lookup fails or the user explicitly
    chooses manual entry.
    """

    def supports(self, language: Language) -> bool:
        return language in ("en", "ja")

    def lookup(self, word: str, language: Language) -> LookupResult:
        entry = VocabularyEntry(
            language=language,
            word=word,
            source_provider="manual",
        )
        return LookupResult(entry=entry, status="ok")
