from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from app.core.errors import CacheError
from app.core.models import Language, normalize_word_key
from app.core.utils import utc_now_str

log = logging.getLogger(__name__)

RecentRow = tuple[str, str, str | None, str]


class RecentLookupStore:
    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

    def delete_recent_entries(self, language: Language, word_keys: Iterable[str]) -> int:
        keys = {normalize_word_key(key, language) for key in word_keys if key}
        if not keys:
            return 0
        ids: list[int] = []
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT id, word, entry_word FROM recent_lookups WHERE language=?",
                    (language,),
                ).fetchall()
                ids = [
                    row["id"]
                    for row in rows
                    if normalize_word_key(row["word"], language) in keys
                    or (
                        row["entry_word"]
                        and normalize_word_key(row["entry_word"], language) in keys
                    )
                ]
                if ids:
                    conn.executemany(
                        "DELETE FROM recent_lookups WHERE id=?",
                        [(row_id,) for row_id in ids],
                    )
        except Exception as exc:
            log.warning("recent delete failed: %s", exc)
            raise CacheError(str(exc)) from exc
        return len(ids)

    def clear_recent(self) -> None:
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM recent_lookups")
        except Exception as exc:
            raise CacheError(str(exc)) from exc

    def snapshot_recent_lookups(self) -> list[RecentRow]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT language, word, entry_word, looked_up_at
                    FROM recent_lookups
                    ORDER BY id ASC
                    """
                ).fetchall()
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return [
            (row["language"], row["word"], row["entry_word"], row["looked_up_at"])
            for row in rows
        ]

    def restore_recent_lookups(self, rows: Iterable[RecentRow]) -> int:
        payload = [
            (language, word, entry_word, looked_up_at)
            for language, word, entry_word, looked_up_at in rows
            if language and word and looked_up_at
        ]
        if not payload:
            return 0
        try:
            with self._conn() as conn:
                conn.executemany(
                    """
                    INSERT INTO recent_lookups(language, word, entry_word, looked_up_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    payload,
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return len(payload)

    def remember_lookup(
        self,
        word: str,
        language: Language,
        entry_word: str | None = None,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO recent_lookups(language, word, entry_word, looked_up_at) "
                    "VALUES(?, ?, ?, ?)",
                    (language, word, entry_word, utc_now_str()),
                )
        except Exception as exc:
            log.warning("recent_lookups insert failed: %s", exc)

    def recent(self, limit: int = 20) -> list[RecentRow]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
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
        except Exception as exc:
            log.warning("recent query failed: %s", exc)
            return []
        return [(r["language"], r["word"], r["entry_word"], r["t"]) for r in rows]
