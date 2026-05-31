"""Coverage for the LookupService routing logic.

Mocks the provider and uses a real CacheStore (isolated via the
JELLY_DICT_HOME tmp dir from conftest.py).
"""
from __future__ import annotations

import pytest

from app.core.errors import UnsupportedLanguageError
from app.core.models import VocabularyEntry
from app.dictionary.base import DictionaryProvider, LookupResult
from app.services.lookup_service import LookupService
from app.storage.cache_store import CacheStore
from app.storage.settings_store import EXCEL_COLUMN_KEYS_DEFAULT, Settings


def _settings(cache_enabled: bool = True) -> Settings:
    return Settings(
        default_excel_dir="",
        excel_path_en="",
        excel_path_ja="",
        default_anki_export_dir="",
        request_delay_seconds=0.0,
        cache_enabled=cache_enabled,
        duplicate_policy="ask",
        excel_columns=list(EXCEL_COLUMN_KEYS_DEFAULT),
    )


class _FakeProvider:
    """Minimal stand-in matching the DictionaryProvider Protocol."""

    def __init__(self, result: LookupResult) -> None:
        self._result = result
        self.calls: list[tuple[str, str]] = []

    def supports(self, language) -> bool:
        return language in ("en", "ja")

    def lookup(self, word: str, language) -> LookupResult:
        self.calls.append((word, language))
        return self._result


def test_unsupported_language_raises(isolated_runtime):
    cache = CacheStore()
    provider = _FakeProvider(LookupResult(status="ok"))
    service = LookupService(provider, cache, _settings())
    with pytest.raises(UnsupportedLanguageError):
        service.lookup("사과")


def test_ambiguous_input_returns_signal_without_calling_provider(isolated_runtime):
    cache = CacheStore()
    provider = _FakeProvider(LookupResult(status="ok"))
    service = LookupService(provider, cache, _settings())

    outcome = service.lookup("apple 月")
    assert outcome.detected_language == "ambiguous"
    assert outcome.asked_user_for_language
    assert provider.calls == []


def test_cache_hit_skips_provider(isolated_runtime):
    cache = CacheStore()
    cached = VocabularyEntry(language="en", word="apple", memo="cached")
    cache.upsert(cached)
    provider = _FakeProvider(LookupResult(status="ok"))
    service = LookupService(provider, cache, _settings(cache_enabled=True))

    outcome = service.lookup("apple")
    assert outcome.from_cache is True
    assert outcome.result.entry is not None
    assert outcome.result.entry.memo == "cached"
    assert provider.calls == [], "provider must not be called on cache hit"


def test_force_refresh_bypasses_cache_and_updates_it(isolated_runtime):
    cache = CacheStore()
    cache.upsert(VocabularyEntry(language="en", word="apple", memo="cached"))
    fresh_entry = VocabularyEntry(language="en", word="apple", memo="fresh")
    provider = _FakeProvider(LookupResult(entry=fresh_entry, status="ok"))
    service = LookupService(provider, cache, _settings(cache_enabled=True))

    outcome = service.lookup("apple", force_refresh=True)

    assert outcome.from_cache is False
    assert provider.calls == [("apple", "en")]
    assert cache.get("apple", "en").memo == "fresh"


def test_cache_miss_calls_provider_and_caches(isolated_runtime):
    cache = CacheStore()
    fresh_entry = VocabularyEntry(language="en", word="banana", memo="fresh")
    provider = _FakeProvider(LookupResult(entry=fresh_entry, status="ok"))
    service = LookupService(provider, cache, _settings(cache_enabled=True))

    outcome = service.lookup("banana")
    assert outcome.from_cache is False
    assert provider.calls == [("banana", "en")]
    # And subsequent lookup should hit the cache.
    outcome2 = service.lookup("banana")
    assert outcome2.from_cache is True
    assert provider.calls == [("banana", "en")]  # unchanged


def test_cache_disabled_always_calls_provider(isolated_runtime):
    cache = CacheStore()
    cache.upsert(VocabularyEntry(language="en", word="apple"))
    provider = _FakeProvider(
        LookupResult(entry=VocabularyEntry(language="en", word="apple"), status="ok")
    )
    service = LookupService(provider, cache, _settings(cache_enabled=False))

    service.lookup("apple")
    service.lookup("apple")
    assert len(provider.calls) == 2


def test_forced_language_overrides_detection(isolated_runtime):
    cache = CacheStore()
    provider = _FakeProvider(
        LookupResult(entry=VocabularyEntry(language="ja", word="apple"), status="ok")
    )
    service = LookupService(provider, cache, _settings())

    service.lookup("apple", forced_language="ja")
    assert provider.calls == [("apple", "ja")]


def test_provider_failure_is_returned_as_lookup_result(isolated_runtime):
    cache = CacheStore()
    provider = _FakeProvider(LookupResult(status="parse_failed", error_detail="boom"))
    service = LookupService(provider, cache, _settings())

    outcome = service.lookup("apple")
    assert outcome.from_cache is False
    assert outcome.result.status == "parse_failed"
    # Failed lookups must NOT be cached.
    assert cache.get("apple", "en") is None
