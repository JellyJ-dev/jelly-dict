from __future__ import annotations

import logging

from app.core.cache_policy import cache_entry_needs_refresh
from app.core.models import VocabularyEntry

log = logging.getLogger(__name__)


def entry_from_cache_json(payload: str) -> VocabularyEntry | None:
    try:
        entry = VocabularyEntry.from_json(payload)
    except Exception as exc:
        log.warning("cache deserialize failed: %s", exc)
        return None
    if entry_needs_parser_refresh(entry):
        log.info("Ignoring stale parser cache entry: %s/%s", entry.language, entry.word)
        return None
    return entry


def entry_needs_parser_refresh(entry: VocabularyEntry) -> bool:
    return cache_entry_needs_refresh(entry)
