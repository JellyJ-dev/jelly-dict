from __future__ import annotations

import logging

from app.core.models import VocabularyEntry

log = logging.getLogger(__name__)


def entry_from_cache_json(payload: str) -> VocabularyEntry | None:
    try:
        entry = VocabularyEntry.from_json(payload)
    except Exception as exc:
        log.warning("cache deserialize failed: %s", exc)
        return None
    return entry
