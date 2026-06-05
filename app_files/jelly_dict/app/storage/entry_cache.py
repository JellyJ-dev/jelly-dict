from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from app.core.errors import CacheError
from app.core.models import Language, VocabularyEntry, normalize_word_key
from app.core.utils import utc_now_str
from app.storage.cache_entry_codec import entry_from_cache_json

log = logging.getLogger(__name__)


class EntryCache:
    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

    def get(self, word: str, language: Language) -> VocabularyEntry | None:
        key = normalize_word_key(word, language)
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT entry_json FROM entries_cache WHERE language=? AND word_key=?",
                    (language, key),
                ).fetchone()
        except Exception as exc:  # never let cache failures kill the app
            log.warning("cache get failed: %s", exc)
            return None
        if not row:
            return None
        return entry_from_cache_json(row["entry_json"])

    def upsert(self, entry: VocabularyEntry) -> None:
        try:
            with self._conn() as conn:
                now = utc_now_str()
                conn.execute(
                    """
                    INSERT INTO entries_cache(language, word_key, word_display, entry_json,
                                              source_url, fetched_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(language, word_key) DO UPDATE SET
                        word_display = excluded.word_display,
                        entry_json   = excluded.entry_json,
                        source_url   = excluded.source_url,
                        updated_at   = excluded.updated_at
                    """,
                    (
                        entry.language,
                        entry.word_key(),
                        entry.word,
                        entry.to_json(),
                        entry.source_url,
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            log.warning("cache upsert failed: %s", exc)
            raise CacheError(str(exc)) from exc

    def clear(self) -> None:
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM entries_cache")
        except Exception as exc:
            raise CacheError(str(exc)) from exc

    def delete_entries(self, language: Language, word_keys: Iterable[str]) -> int:
        keys = [key for key in word_keys if key]
        if not keys:
            return 0
        try:
            with self._conn() as conn:
                conn.executemany(
                    "DELETE FROM entries_cache WHERE language=? AND word_key=?",
                    [(language, key) for key in keys],
                )
        except Exception as exc:
            log.warning("cache delete failed: %s", exc)
            raise CacheError(str(exc)) from exc
        return len(keys)
