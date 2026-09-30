"""Coordinates language detection, cache, and the active provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.diagnostics import DiagnosticResult, diagnostic_operation
from app.core.domain import LookupResult
from app.core.errors import UnsupportedLanguageError
from app.core.language_detector import detect_language
from app.core.models import Language
from app.services.ports import DictionaryPort, LookupCachePort, LookupSettingsPort

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
        provider: DictionaryPort,
        cache: LookupCachePort,
        settings: LookupSettingsPort,
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
        persist: bool = True,
    ) -> LookupOutcome:
        with diagnostic_operation("lookup") as diagnostic:
            outcome = self._lookup(
                word,
                forced_language,
                force_refresh=force_refresh,
                persist=persist,
            )
            diagnostic.finish(_lookup_diagnostic_result(outcome))
            return outcome

    def _lookup(
        self,
        word: str,
        forced_language: Language | None = None,
        *,
        force_refresh: bool = False,
        persist: bool = True,
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
        provider_id = str(getattr(self._settings, "provider", "naver_crawler"))

        if self._settings.cache_enabled and not force_refresh:
            cached = self._cache.get(word, language, provider_id=provider_id)
            if cached is not None:
                self._cache.remember_lookup(word, language, entry_word=cached.word)
                return LookupOutcome(
                    result=LookupResult(entry=cached, status="ok", raw_url=cached.source_url),
                    detected_language=language,
                    from_cache=True,
                )

        fresh_lookup = getattr(self._provider, "lookup_fresh", None)
        result = (
            fresh_lookup(word, language)
            if force_refresh and callable(fresh_lookup)
            else self._provider.lookup(word, language)
        )
        entry_word = result.entry.word if result.ok and result.entry else None
        if result.ok and self._settings.cache_enabled and persist:
            assert result.entry is not None
            try:
                self._cache.upsert(result.entry, provider_id=provider_id)
            except Exception as exc:  # cache failures must not block the lookup
                log.warning("cache upsert failed: %s", exc)
        if persist:
            self._cache.remember_lookup(word, language, entry_word=entry_word)
        return LookupOutcome(result=result, detected_language=language, from_cache=False)


def _lookup_diagnostic_result(outcome: LookupOutcome) -> DiagnosticResult:
    if outcome.from_cache:
        return "cache_hit"
    statuses: dict[str, DiagnosticResult] = {
        "ok": "success",
        "not_found": "not_found",
        "parse_failed": "parse_failed",
        "network_error": "network_error",
        "rate_limited": "rate_limited",
        "unsupported": "unsupported",
    }
    return statuses.get(outcome.result.status, "failed")
