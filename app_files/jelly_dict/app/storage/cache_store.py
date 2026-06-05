from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from app.core.cache_policy import cache_entry_needs_refresh
from app.core.errors import CacheError
from app.core.models import Language, VocabularyEntry, normalize_word_key
from app.core.utils import utc_now_str
from app.storage.sqlite_store import open_db

log = logging.getLogger(__name__)

class CacheStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def _conn(self):
        return open_db(self._db_path)

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
        return _entry_from_cache_json(row["entry_json"])

    def upsert(self, entry: VocabularyEntry) -> None:
        try:
            with self._conn() as conn:
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
                        utc_now_str(),
                        utc_now_str(),
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
        """Drop cached entries matching (language, word_key). Pre-normalized
        keys expected. Returns the number of rows attempted (not affected).
        Errors are logged and re-raised as CacheError."""
        keys = [k for k in word_keys if k]
        if not keys:
            return 0
        try:
            with self._conn() as conn:
                conn.executemany(
                    "DELETE FROM entries_cache WHERE language=? AND word_key=?",
                    [(language, k) for k in keys],
                )
        except Exception as exc:
            log.warning("cache delete failed: %s", exc)
            raise CacheError(str(exc)) from exc
        return len(keys)

    def delete_recent_entries(self, language: Language, word_keys: Iterable[str]) -> int:
        keys = {normalize_word_key(k, language) for k in word_keys if k}
        if not keys:
            return 0
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
        """Wipe the recent_lookups list without touching the entry cache."""
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM recent_lookups")
        except Exception as exc:
            raise CacheError(str(exc)) from exc

    def snapshot_recent_lookups(self) -> list[tuple[str, str, str | None, str]]:
        """Return raw recent rows so a destructive clear can be undone."""
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

    def restore_recent_lookups(
        self,
        rows: Iterable[tuple[str, str, str | None, str]],
    ) -> int:
        """Append previously snapshotted recent rows without touching cache."""
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

    def set_state(self, key: str, value: str) -> None:
        key = (key or "").strip()
        if not key:
            return
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO app_state(key, value, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, value, utc_now_str()),
                )
        except Exception as exc:
            log.warning("cache state set failed: %s", exc)

    def get_state(self, key: str) -> str | None:
        key = (key or "").strip()
        if not key:
            return None
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM app_state WHERE key=?",
                    (key,),
                ).fetchone()
        except Exception as exc:
            log.warning("cache state get failed: %s", exc)
            return None
        return str(row["value"]) if row else None

    def remember_lookup(
        self,
        word: str,
        language: Language,
        entry_word: str | None = None,
    ) -> None:
        """Record a lookup. `entry_word` is the canonical headword from
        the dictionary entry (may differ from the user's typed query),
        used to recover the cached entry for the recent-list hint."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO recent_lookups(language, word, entry_word, looked_up_at) "
                    "VALUES(?, ?, ?, ?)",
                    (language, word, entry_word, utc_now_str()),
                )
        except Exception as exc:
            log.warning("recent_lookups insert failed: %s", exc)

    def recent(self, limit: int = 20) -> list[tuple[str, str, str | None, str]]:
        """Return [(language, word, entry_word, looked_up_at)]."""
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

    def recent_with_entries(
        self, limit: int = 20
    ) -> list[tuple[str, str, str | None, str, VocabularyEntry | None]]:
        """Return recent lookups with their cached entry attached.

        Equivalent to calling recent() then get() per row, but uses a
        single LEFT JOIN query — saves N round-trips when refreshing the
        recent list. Falls back to per-row lookup on rare cases where
        the entry_word stored in recent_lookups doesn't match the cache
        key (e.g. legacy rows from before the entry_word column).

        Tuple shape: (language, word, entry_word, looked_up_at, cached_entry).
        """
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

                # Collect candidate (language, key) pairs to fetch in one go.
                # Prefer entry_word; fall back to typed word.
                candidates: list[tuple[str, str, str]] = []
                for row in grouped:
                    lang = row["language"]
                    typed = row["word"]
                    canonical = row["entry_word"]
                    primary_key = normalize_word_key(canonical or typed, lang)  # type: ignore[arg-type]
                    candidates.append((lang, primary_key, typed))

                # Pull all matching cache entries in a single query.
                placeholders = ",".join("(?, ?)" for _ in candidates)
                params: list[str] = []
                for lang, key, _ in candidates:
                    params.extend([lang, key])
                cache_rows = conn.execute(
                    f"""
                    SELECT language, word_key, entry_json
                    FROM entries_cache
                    WHERE (language, word_key) IN ({placeholders})
                    """,
                    params,
                ).fetchall() if candidates else []
        except Exception as exc:
            log.warning("recent_with_entries query failed: %s", exc)
            # Graceful fallback: callers can still call recent() + get()
            return [(*row, None) for row in self.recent(limit)]

        cache_index: dict[tuple[str, str], VocabularyEntry] = {}
        for cr in cache_rows:
            entry = _entry_from_cache_json(cr["entry_json"])
            if entry is not None:
                cache_index[(cr["language"], cr["word_key"])] = entry

        out: list[tuple[str, str, str | None, str, VocabularyEntry | None]] = []
        for row, (lang, key, typed) in zip(grouped, candidates):
            entry = cache_index.get((lang, key))
            # If primary key missed, try the alternate key (typed vs canonical).
            if entry is None and row["entry_word"]:
                alt = normalize_word_key(typed, lang)  # type: ignore[arg-type]
                entry = cache_index.get((lang, alt))
                if entry is None:
                    # final fallback: per-row get (rare)
                    entry = self.get(typed, lang)  # type: ignore[arg-type]
            out.append((lang, typed, row["entry_word"], row["t"], entry))
        return out


def _entry_from_cache_json(payload: str) -> VocabularyEntry | None:
    try:
        entry = VocabularyEntry.from_json(payload)
    except Exception as exc:
        log.warning("cache deserialize failed: %s", exc)
        return None
    if _entry_needs_parser_refresh(entry):
        log.info("Ignoring stale parser cache entry: %s/%s", entry.language, entry.word)
        return None
    return entry


def _entry_needs_parser_refresh(entry: VocabularyEntry) -> bool:
    return cache_entry_needs_refresh(entry)
