"""Coordinates language detection, cache, and the active provider."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.errors import UnsupportedLanguageError
from app.core.language_detector import detect_language
from app.core.models import Language, VocabularyEntry
from app.dictionary.base import DictionaryProvider, LookupResult
from app.storage.cache_store import CacheStore
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)


@dataclass
class LookupOutcome:
    result: LookupResult
    detected_language: str
    from_cache: bool
    asked_user_for_language: bool = False


class LookupService:
    def __init__(
        self,
        provider: DictionaryProvider,
        cache: CacheStore,
        settings: Settings,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._settings = settings

    def lookup(
        self,
        word: str,
        forced_language: Language | None = None,
        *,
        force_refresh: bool = False,
    ) -> LookupOutcome:
        word = (word or "").strip()
        if not word:
            return LookupOutcome(
                result=LookupResult(status="not_found", error_detail="empty input"),
                detected_language="unsupported",
                from_cache=False,
            )

        detected = forced_language or detect_language(word)
        if detected == "unsupported":
            raise UnsupportedLanguageError(word)
        if detected == "ambiguous" and forced_language is None:
            return LookupOutcome(
                result=LookupResult(status="not_found", error_detail="ambiguous"),
                detected_language="ambiguous",
                from_cache=False,
                asked_user_for_language=True,
            )

        language: Language = forced_language or detected  # type: ignore[assignment]

        if self._settings.cache_enabled and not force_refresh:
            cached = self._cache.get(word, language)
            if cached is not None:
                self._cache.remember_lookup(word, language, entry_word=cached.word)
                return LookupOutcome(
                    result=LookupResult(entry=cached, status="ok", raw_url=cached.source_url),
                    detected_language=language,
                    from_cache=True,
                )

        result = self._provider.lookup(word, language)
        entry_word = result.entry.word if result.ok and result.entry else None
        if result.ok and self._settings.cache_enabled:
            assert result.entry is not None
            try:
                self._cache.upsert(result.entry)
            except Exception as exc:  # cache failures must not block the lookup
                log.warning("cache upsert failed: %s", exc)
        self._cache.remember_lookup(word, language, entry_word=entry_word)
        return LookupOutcome(result=result, detected_language=language, from_cache=False)


def empty_entry(word: str, language: Language) -> VocabularyEntry:
    """Helper for the manual-entry fallback path."""
    return VocabularyEntry(language=language, word=word, source_provider="manual")
