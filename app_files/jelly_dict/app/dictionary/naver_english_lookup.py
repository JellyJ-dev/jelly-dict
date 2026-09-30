"""Bounded English lookup using the responses emitted by Naver's own SPA."""

from __future__ import annotations

import logging
import time

from app.core.domain import LookupResult
from app.core.errors import NetworkError, ParseError, RateLimitedError
from app.dictionary import naver_english, naver_english_related, naver_english_reverse
from app.dictionary import naver_english_data as data
from app.dictionary.playwright_client import FetchTimings, JsonResponseMatch

log = logging.getLogger(__name__)
MAX_DETAIL_REQUESTS = 3
DETAIL_BUDGET_SECONDS = 8.0
PHRASE_SEARCH_TIMEOUT_MS = 2_500


def lookup(client, word: str, *, force_refresh: bool = False) -> tuple[LookupResult, FetchTimings]:
    started = time.perf_counter()
    total = FetchTimings()

    def fetch(url, match, **kwargs):
        nonlocal total
        result = client.fetch_naver_json(url, match, **kwargs)
        t = result.timings
        total = FetchTimings(
            navigation_ms=total.navigation_ms + t.navigation_ms,
            selector_ms=total.selector_ms + t.selector_ms,
            content_ms=total.content_ms + t.content_ms,
            total_ms=total.total_ms + t.total_ms,
        )
        return result.data

    search_url = naver_english.lookup_url(word)
    payload = fetch(
        search_url, JsonResponseMatch(data.SEARCH_PATH, "query", word), force_refresh=force_refresh
    )
    effective_word = data.search_word(payload, word)
    correction = effective_word if data.word_key(effective_word) != data.word_key(word) else None

    def found(entry, url):
        return LookupResult(entry=entry, status="ok", raw_url=url, suggested_word=correction), total

    def search_fallback(response, query):
        return data.open_search_entry(response, query) or naver_english_reverse.search_entry(
            response, query
        )

    original_payload = payload

    def verified_search_entry(entry_id=None):
        # A detail timeout must not switch to a sparse OPEN/KOEN definition
        # while the selected publisher's senses and examples are in WORD.
        preferred_ids = [entry_id] if entry_id else []
        preferred_ids.extend(c.entry_id for c in candidates)
        for preferred_id in dict.fromkeys(preferred_ids):
            entry = data.search_result_entry(original_payload, word, "WORD", entry_id=preferred_id)
            if entry:
                return entry
        return search_fallback(original_payload, word)

    candidates = data.search_candidates(payload, word)
    # An exact adjective (e.g. nuanced) is more specific than its noun lemma.
    if candidates and data.phrase_key(candidates[0].word) != data.phrase_key(effective_word):
        entry = data.open_search_entry(payload, word)
        if entry:
            return found(entry, entry.source_url)
    if not candidates:
        entry = search_fallback(payload, word) or data.search_result_entry(
            payload, word, "OPEN", allow_article=True
        )
        if entry:
            log.info("naver English search result word=%s source=%s", word, entry.source_url)
            return found(entry, entry.source_url)
        related = naver_english_related.search_words(payload, word)
        fallback = data.passive_query(effective_word)
        if fallback:
            log.info("naver English phrase fallback word=%s query=%s", word, fallback)
            fallback_url = naver_english.lookup_url(fallback)
            payload = fetch(
                fallback_url,
                JsonResponseMatch(data.SEARCH_PATH, "query", fallback),
                timeout_ms=PHRASE_SEARCH_TIMEOUT_MS,
            )
            candidates = data.search_candidates(payload, fallback)
            if not candidates:
                entry = search_fallback(payload, fallback)
                if entry:
                    return found(entry, entry.source_url)
                for candidate in naver_english_related.search_words(payload, fallback):
                    if data.word_key(candidate) not in {data.word_key(w) for w in related}:
                        related.append(candidate)
        if not candidates:
            related = related[:5]
            log.info("naver English no exact entry word=%s related=%s", word, related)
            return LookupResult(
                status="not_found", raw_url=search_url, related_words=related
            ), total
    # Alternative exact headwords take precedence over lemma/related matches.
    canonical = candidates[0].word
    candidates = [c for c in candidates if data.word_form(c.word) == data.word_form(canonical)]
    if not candidates[0].has_definition:
        entry = naver_english_reverse.search_entry(
            original_payload, word
        ) or data.open_search_entry(original_payload, word)
        if entry:
            return found(entry, entry.source_url)
    pending = [(c.entry_id, None) for c in candidates]
    visited: set[str] = set()
    deadline = time.monotonic() + DETAIL_BUDGET_SECONDS
    supporting = None
    supporting_parts: frozenset[str] = frozenset()
    while pending and len(visited) < MAX_DETAIL_REQUESTS:
        entry_id, required_parts = pending.pop(0)
        if entry_id in visited:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        visited.add(entry_id)
        url = naver_english.ENTRY_URL.format(id=entry_id)
        try:
            detail = fetch(
                url,
                JsonResponseMatch(data.ENTRY_PATH, "entryId", entry_id),
                timeout_ms=max(1, min(4_000, int(remaining * 1000))),
            )
        except RateLimitedError:
            raise
        except NetworkError:
            entry = verified_search_entry(entry_id)
            if entry:
                log.info("naver English detail unavailable; using verified search word=%s", word)
                return found(entry, entry.source_url)
            raise
        try:
            raw = data.entry_payload(detail, entry_id, canonical)
        except ParseError:
            # A publisher group can contain a different form; never adopt it.
            if required_parts is not None:
                continue
            raise
        parts = data.entry_parts(raw)
        if required_parts is not None and not (parts & required_parts):
            continue
        entry = data.parse_entry(raw, canonical)
        if entry.meaning_groups:
            if supporting is not None and parts & supporting_parts:
                if not entry.reading:
                    entry.reading = supporting.reading
                if not entry.examples_flat and supporting.examples_flat:
                    entry.examples_flat = supporting.examples_flat
                    entry.meaning_groups[0].senses[0].sub_senses[0].examples = entry.examples_flat
            log.info(
                "naver English result word=%s entry=%s details=%s elapsed_ms=%.1f",
                word,
                entry_id,
                len(visited),
                (time.perf_counter() - started) * 1000,
            )
            return found(entry, url)
        if supporting is None:
            supporting = entry
            supporting_parts = parts
        if parts:
            for peer_id in data.alternate_ids(raw):
                if peer_id not in visited:
                    pending.append((peer_id, parts))
    entry = verified_search_entry()
    if entry:
        return found(entry, entry.source_url)
    return LookupResult(
        status="parse_failed",
        raw_url=search_url,
        error_detail="No definition in matching dictionary entries",
    ), total
