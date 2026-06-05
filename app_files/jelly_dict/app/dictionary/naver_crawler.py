"""Routing dictionary provider that drives the English / Japanese parsers."""
from __future__ import annotations

import logging

from app.core.errors import (
    DomainNotAllowedError,
    HttpStatusError,
    NetworkError,
    RateLimitedError,
)
from app.core.models import Language, VocabularyEntry
from app.dictionary import naver_english, naver_japanese
from app.dictionary.base import DictionaryProvider, LookupResult
from app.dictionary.parser_utils import common_prefix_len
from app.dictionary.playwright_client import PlaywrightClient

log = logging.getLogger(__name__)


class NaverDictionaryCrawlerProvider(DictionaryProvider):
    def __init__(self, client: PlaywrightClient | None = None) -> None:
        self._client = client or PlaywrightClient()

    @property
    def client(self) -> PlaywrightClient:
        return self._client

    def supports(self, language: Language) -> bool:
        return language in ("en", "ja")

    def close(self) -> None:
        try:
            self._client.stop()
        except Exception as exc:
            log.warning("client stop failed: %s", exc)

    def lookup(self, word: str, language: Language) -> LookupResult:
        if not self.supports(language):
            return LookupResult(status="unsupported", error_detail=language)

        if language == "en":
            url = naver_english.lookup_url(word)
            wait_for = naver_english.WAIT_SELECTOR
            parser = naver_english.parse_with_canonical
        else:
            url = naver_japanese.lookup_url(word)
            wait_for = naver_japanese.WAIT_SELECTOR
            parser = naver_japanese.parse_with_canonical

        try:
            html = self._client.fetch(url, wait_selector=wait_for)
        except RateLimitedError as exc:
            return LookupResult(status="rate_limited", raw_url=url, error_detail=str(exc))
        except HttpStatusError as exc:
            return LookupResult(status="network_error", raw_url=url, error_detail=str(exc))
        except DomainNotAllowedError as exc:
            return LookupResult(status="network_error", raw_url=url, error_detail=str(exc))
        except NetworkError as exc:
            return LookupResult(status="network_error", raw_url=url, error_detail=str(exc))

        try:
            entry, canonical = parser(html, word=word, source_url=url)
        except Exception as exc:
            log.exception("parser crashed")
            return LookupResult(status="parse_failed", raw_url=url, error_detail=str(exc))

        if entry is None:
            return LookupResult(status="parse_failed", raw_url=url)

        suggestion = _suggestion_if_unrelated(word, canonical, language)
        return LookupResult(
            entry=entry, status="ok", raw_url=url, suggested_word=suggestion
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
        t = typed_norm.lower()
        c = canonical_norm.lower()
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

