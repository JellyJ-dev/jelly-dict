from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.core.models import Language, VocabularyEntry, normalize_word_key
from app.storage.cache_entry_codec import entry_from_cache_json
from app.storage.recent_store import RecentLookupStore

log = logging.getLogger(__name__)

RecentEntryRow = tuple[str, str, str | None, str, VocabularyEntry | None]


class RecentEntryLookup:
    def __init__(
        self,
        conn_factory: Callable[[], Any],
        recent_store: RecentLookupStore,
        get_entry: Callable[[str, Language], VocabularyEntry | None],
    ) -> None:
        self._conn = conn_factory
        self._recent_store = recent_store
        self._get_entry = get_entry

    def recent_with_entries(self, limit: int = 20) -> list[RecentEntryRow]:
        try:
            with self._conn() as conn:
                grouped = conn.execute(
                    """
                    SELECT language, word,
                           MAX(entry_word) AS entry_word,
                           MAX(looked_up_at) AS t
                    FROM recent_lookups
                    GROUP BY language, word
                    ORDER BY t DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

                if not grouped:
                    return []

                candidates: list[tuple[str, str, str]] = []
                for row in grouped:
                    lang = row["language"]
                    typed = row["word"]
                    canonical = row["entry_word"]
                    key = normalize_word_key(canonical or typed, lang)  # type: ignore[arg-type]
                    candidates.append((lang, key, typed))

                placeholders = ",".join("(?, ?)" for _ in candidates)
                params: list[str] = []
                for lang, key, _ in candidates:
                    params.extend([lang, key])
                cache_rows = (
                    conn.execute(
                        f"""
                        SELECT language, word_key, entry_json
                        FROM entries_cache
                        WHERE (language, word_key) IN ({placeholders})
                        """,
                        params,
                    ).fetchall()
                    if candidates
                    else []
                )
        except Exception as exc:
            log.warning("recent_with_entries query failed: %s", exc)
            return [(*row, None) for row in self._recent_store.recent(limit)]

        cache_index: dict[tuple[str, str], VocabularyEntry] = {}
        for row in cache_rows:
            entry = entry_from_cache_json(row["entry_json"])
            if entry is not None:
                cache_index[(row["language"], row["word_key"])] = entry

        out: list[RecentEntryRow] = []
        for row, (lang, key, typed) in zip(grouped, candidates):
            entry = cache_index.get((lang, key))
            if entry is None and row["entry_word"]:
                alt = normalize_word_key(typed, lang)  # type: ignore[arg-type]
                entry = cache_index.get((lang, alt))
                if entry is None:
                    entry = self._get_entry(typed, lang)  # type: ignore[arg-type]
            out.append((lang, typed, row["entry_word"], row["t"], entry))
        return out
