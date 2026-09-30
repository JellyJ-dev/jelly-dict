"""Routing dictionary provider that drives the English / Japanese parsers."""

from __future__ import annotations

import logging
import time

from app.core.errors import (
    DomainNotAllowedError,
    HttpStatusError,
    NetworkError,
    ParseError,
    RateLimitedError,
)
from app.core.models import Language
from app.dictionary import naver_english, naver_english_lookup, naver_japanese
from app.dictionary.base import DictionaryProvider, LookupResult
from app.dictionary.parser_utils import common_prefix_len
from app.dictionary.playwright_client import FetchResult, FetchTimings, PlaywrightClient

log = logging.getLogger(__name__)


class NaverDictionaryCrawlerProvider(DictionaryProvider):
    def __init__(self, client: PlaywrightClient | None = None) -> None:
        self._client = client or PlaywrightClient()
        self._last_timings = FetchTimings()

    @property
    def client(self) -> PlaywrightClient:
        return self._client

    @property
    def last_timings(self) -> FetchTimings:
        return self._last_timings

    def supports(self, language: Language) -> bool:
        return language in ("en", "ja")

    def prewarm(self) -> None:
        self._client.start()

    def cancel_prewarm(self) -> None:
        self._client.stop()

    def close(self) -> None:
        try:
            self._client.stop()
        except Exception as exc:
            log.warning("client stop failed: %s", exc)

    def lookup(self, word: str, language: Language) -> LookupResult:
        return self._lookup(word, language)

    def lookup_fresh(self, word: str, language: Language) -> LookupResult:
        return self._lookup(word, language, force_refresh=True)

    def _lookup(
        self, word: str, language: Language, *, force_refresh: bool = False
    ) -> LookupResult:
        if not self.supports(language):
            return LookupResult(status="unsupported", error_detail=language)

        if language == "en" and callable(getattr(self._client, "fetch_naver_json", None)):
            try:
                result, timings = naver_english_lookup.lookup(
                    self._client,
                    word,
                    force_refresh=force_refresh,
                )
            except RateLimitedError as exc:
                return LookupResult(status="rate_limited", error_detail=str(exc))
            except NetworkError as exc:
                return LookupResult(status="network_error", error_detail=str(exc))
            except ParseError as exc:
                return LookupResult(status="parse_failed", error_detail=str(exc))
            self._record_timings(timings, 0.0)
            if result.entry and not result.suggested_word:
                result.suggested_word = _suggestion_if_unrelated(word, result.entry.word, language)
            return result

        if language == "en":
            url = naver_english.lookup_url(word)
            wait_for = naver_english.WAIT_SELECTOR
            parser = naver_english.parse_with_canonical
        else:
            url = naver_japanese.lookup_url(word)
            wait_for = naver_japanese.WAIT_SELECTOR
            parser = naver_japanese.parse_with_canonical

        try:
            fetched = self._fetch_page(url, wait_for)
        except RateLimitedError as exc:
            return LookupResult(status="rate_limited", raw_url=url, error_detail=str(exc))
        except HttpStatusError as exc:
            return LookupResult(status="network_error", raw_url=url, error_detail=str(exc))
        except DomainNotAllowedError as exc:
            return LookupResult(status="network_error", raw_url=url, error_detail=str(exc))
        except NetworkError as exc:
            return LookupResult(status="network_error", raw_url=url, error_detail=str(exc))

        fetch_timings = fetched.timings
        parse_ms = 0.0
        parse_started = time.perf_counter()
        try:
            entry, canonical = parser(fetched.html, word=word, source_url=url)
        except Exception as exc:
            parse_ms += (time.perf_counter() - parse_started) * 1000.0
            self._record_timings(fetch_timings, parse_ms)
            log.exception("parser crashed")
            return LookupResult(status="parse_failed", raw_url=url, error_detail=str(exc))
        parse_ms += (time.perf_counter() - parse_started) * 1000.0

        if language == "en":
            entry_url = naver_english.primary_entry_url(fetched.html, word)
            if entry_url and entry_url != url:
                try:
                    enriched = self._fetch_page(entry_url, naver_english.ENTRY_WAIT_SELECTOR)
                except (
                    RateLimitedError,
                    HttpStatusError,
                    DomainNotAllowedError,
                    NetworkError,
                ) as exc:
                    log.info("naver entry enrichment skipped: %s", exc)
                else:
                    fetch_timings = _combine_fetch_timings(fetch_timings, enriched.timings)
                    parse_started = time.perf_counter()
                    try:
                        enriched_entry, enriched_canonical = parser(
                            enriched.html,
                            word=word,
                            source_url=entry_url,
                        )
                    except Exception as exc:
                        log.info("naver entry enrichment parse skipped: %s", exc)
                    else:
                        if enriched_entry is not None:
                            if entry is not None:
                                if not enriched_entry.reading:
                                    enriched_entry.reading = entry.reading
                                if not enriched_entry.pronunciation_audio_url:
                                    enriched_entry.pronunciation_audio_url = (
                                        entry.pronunciation_audio_url
                                    )
                            entry = enriched_entry
                            canonical = enriched_canonical
                            url = entry_url
                    finally:
                        parse_ms += (time.perf_counter() - parse_started) * 1000.0

        self._record_timings(fetch_timings, parse_ms)

        if entry is None:
            return LookupResult(status="parse_failed", raw_url=url)

        suggestion = _suggestion_if_unrelated(word, canonical, language)
        return LookupResult(entry=entry, status="ok", raw_url=url, suggested_word=suggestion)

    def _fetch_page(self, url: str, wait_selector: str) -> FetchResult:
        fetch_with_metrics = getattr(self._client, "fetch_with_metrics", None)
        if callable(fetch_with_metrics):
            return fetch_with_metrics(url, wait_selector=wait_selector)
        fetch_started = time.perf_counter()
        html = self._client.fetch(url, wait_selector=wait_selector)
        elapsed_ms = (time.perf_counter() - fetch_started) * 1000.0
        return FetchResult(
            html,
            FetchTimings(
                navigation_ms=elapsed_ms,
                total_ms=elapsed_ms,
            ),
        )

    def _record_timings(self, timings: FetchTimings, parse_ms: float) -> None:
        self._last_timings = timings.with_parse(parse_ms)
        log.info(
            "naver_lookup_timing navigation_ms=%.1f dom_ready_ms=%.1f "
            "selector_ms=%.1f content_ms=%.1f parse_ms=%.1f total_ms=%.1f",
            self._last_timings.navigation_ms,
            self._last_timings.dom_ready_ms,
            self._last_timings.selector_ms,
            self._last_timings.content_ms,
            self._last_timings.parse_ms,
            self._last_timings.total_ms,
        )


def _combine_fetch_timings(first: FetchTimings, second: FetchTimings) -> FetchTimings:
    return FetchTimings(
        navigation_ms=first.navigation_ms + second.navigation_ms,
        dom_ready_ms=first.dom_ready_ms + second.dom_ready_ms,
        selector_ms=first.selector_ms + second.selector_ms,
        text_ms=first.text_ms + second.text_ms,
        content_ms=first.content_ms + second.content_ms,
        total_ms=first.total_ms + second.total_ms,
    )


def _suggestion_if_unrelated(typed: str, canonical: str, language: Language) -> str | None:
    """Return canonical headword as a 'did you mean' hint only when the
    dictionary returned something genuinely unrelated to the query.

    We always save the canonical (lemma) form, so simple inflections
    (running -> run, instantiates -> instantiate) and variant spellings
    don't need a confirmation. Only ask the user when the dictionary's
    headword shares almost nothing with what they typed — that's the
    typo / wrong-language case.
    """
    if not canonical or not typed:
        return None
    typed_norm = typed.strip()
    canonical_norm = canonical.strip()
    if not typed_norm or not canonical_norm:
        return None
    if language == "en":
        t = " ".join(typed_norm.lower().replace("’", "'").split())
        c = " ".join(canonical_norm.lower().replace("’", "'").split())
        if t == c:
            return None
        # Substring either way → inflection or variant. Save silently.
        if t in c or c in t:
            return None
        # Common prefix at least 4 chars → likely the same root.
        prefix = common_prefix_len(t, c)
        if prefix >= 4 or prefix >= max(len(t), len(c)) // 2:
            return None
        return canonical_norm
    # Japanese: split canonical on the · separator and treat each form
    # as an acceptable variant.
    return naver_japanese.did_you_mean(typed_norm, canonical_norm)
