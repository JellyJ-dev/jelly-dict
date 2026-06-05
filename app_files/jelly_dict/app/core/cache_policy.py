from __future__ import annotations

from app.core.models import VocabularyEntry, sanitize_meaning_gloss


def cache_entry_needs_refresh(entry: VocabularyEntry) -> bool:
    if entry.source_provider != "naver_en":
        return False
    for group in entry.meaning_groups:
        for sense in group.senses:
            gloss = (sense.gloss or "").strip()
            if not gloss:
                continue
            cleaned = sanitize_meaning_gloss(gloss, "en")
            if not cleaned or cleaned != gloss:
                return True
    return False
