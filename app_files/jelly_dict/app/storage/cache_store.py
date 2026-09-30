import json
import logging
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType

from app.core.cache_policy import cache_spelling_matches
from app.core.domain import EntryRef
from app.core.models import Language, VocabularyEntry, normalize_word_key
from app.storage.anki_delete_outbox import AnkiDeleteOperation, AnkiDeleteOutbox
from app.storage.app_state_store import AppStateStore
from app.storage.cache_entry_codec import entry_from_cache_json
from app.storage.entry_cache import EntryCache, cache_row_is_usable
from app.storage.recent_entry_lookup import RecentEntryLookup, RecentEntryRow
from app.storage.recent_store import RecentLookupStore, RecentRow
from app.storage.saved_entry_projection import (
    SavedEntryProjectionStore,
    SavedProjectionRecord,
)
from app.storage.sqlite_store import open_db

log = logging.getLogger(__name__)


class CacheStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._connection = open_db(self._db_path, check_same_thread=False)
        self._closed = False
        self._entries = EntryCache(self._conn)
        self._saved_projections = SavedEntryProjectionStore(self._conn)
        self._anki_delete_outbox = AnkiDeleteOutbox(self._conn)
        self._recent = RecentLookupStore(self._conn)
        self._state = AppStateStore(self._conn)
        self._recent_entries = RecentEntryLookup(self._conn, self._recent, self.get)

    def _conn(self):
        return _LockedConnection(self._connection, self._lock)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def get(
        self,
        word: str,
        language: Language,
        *,
        provider_id: str | None = None,
    ) -> VocabularyEntry | None:
        return self._entries.get(word, language, provider_id=provider_id)

    def get_many(
        self,
        keys: list[tuple[str, Language]],
        *,
        workbook_path: Path | None = None,
        refs: list[EntryRef | None] | None = None,
    ) -> list[VocabularyEntry | None]:
        """Load export enrichment for many rows with one SQLite SELECT.

        Exact saved-row projections take precedence over provider lookup cache
        entries.  JSON1 keeps the request set in one bound parameter, avoiding
        SQLite's variable-count limit for 5,000-row wordbooks.
        """
        if not keys:
            return []
        if refs is None:
            refs = [None] * len(keys)
        if len(refs) != len(keys):
            raise ValueError("refs and keys must have the same length")
        workbook_key = (
            str(Path(workbook_path).expanduser().resolve(strict=False))
            if workbook_path is not None
            else ""
        )
        request_json = json.dumps(
            [
                {
                    "ordinal": ordinal,
                    "language": language,
                    "word_key": normalize_word_key(word, language),
                    "row_number": ref.row_number if ref is not None else -1,
                    "row_identity": ref.identity if ref is not None else "",
                }
                for ordinal, ((word, language), ref) in enumerate(zip(keys, refs))
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            with self._conn() as connection:
                rows = connection.execute(
                    """
                    WITH requested AS (
                        SELECT
                            CAST(json_extract(value, '$.ordinal') AS INTEGER) AS ordinal,
                            json_extract(value, '$.language') AS language,
                            json_extract(value, '$.word_key') AS word_key,
                            CAST(json_extract(value, '$.row_number') AS INTEGER) AS row_number,
                            json_extract(value, '$.row_identity') AS row_identity
                        FROM json_each(?)
                    )
                    SELECT requested.ordinal,
                           saved.entry_json AS saved_json,
                           lookup.entry_json AS lookup_json,
                           lookup.provider_id AS provider_id,
                           lookup.provider_schema_version AS provider_schema_version,
                           lookup.parser_id AS parser_id,
                           lookup.parser_schema_version AS parser_schema_version
                    FROM requested
                    LEFT JOIN saved_entry_projections AS saved
                      ON saved.workbook_path=?
                     AND saved.language=requested.language
                     AND saved.word_key=requested.word_key
                     AND saved.row_number=requested.row_number
                     AND saved.row_identity=requested.row_identity
                    LEFT JOIN entries_cache AS lookup
                      ON lookup.language=requested.language
                     AND lookup.word_key=requested.word_key
                    ORDER BY requested.ordinal
                    """,
                    (request_json, workbook_key),
                ).fetchall()
        except Exception as exc:
            # Cache enrichment is optional; Excel remains the source of truth.
            log.warning("cache get_many failed: %s", exc)
            return [None] * len(keys)
        by_ordinal: dict[int, VocabularyEntry | None] = {}
        for row in rows:
            entry = None
            if row["saved_json"]:
                try:
                    entry = VocabularyEntry.from_json(row["saved_json"])
                except Exception as exc:
                    log.warning("saved projection batch decode failed: %s", exc)
            elif row["lookup_json"] and cache_row_is_usable(
                row, keys[int(row["ordinal"])][1], None
            ):
                try:
                    entry = entry_from_cache_json(row["lookup_json"])
                    if entry and not cache_spelling_matches(keys[int(row["ordinal"])][0], entry):
                        entry = None
                except Exception as exc:
                    log.warning("cache get_many decode failed: %s", exc)
            by_ordinal[int(row["ordinal"])] = entry
        return [by_ordinal.get(index) for index in range(len(keys))]

    def upsert(
        self,
        entry: VocabularyEntry,
        *,
        provider_id: str | None = None,
    ) -> None:
        self._entries.upsert(entry, provider_id=provider_id)

    def clear(self) -> None:
        self._entries.clear()
        self._saved_projections.clear()

    def delete_entries(self, language: Language, word_keys: Iterable[str]) -> int:
        return self._entries.delete_entries(language, word_keys)

    def get_saved_projection(
        self,
        path: Path,
        ref: EntryRef,
    ) -> VocabularyEntry | None:
        return self._saved_projections.get(path, ref)

    def latest_saved_projection(
        self,
        path: Path,
        word: str,
        language: Language,
    ) -> SavedProjectionRecord | None:
        return self._saved_projections.latest(path, word, language)

    def upsert_saved_projection(
        self,
        path: Path,
        ref: EntryRef,
        entry: VocabularyEntry,
    ) -> None:
        self._saved_projections.upsert(path, ref, entry)

    def snapshot_saved_projections(
        self,
        path: Path,
        refs: Iterable[EntryRef],
    ) -> tuple[SavedProjectionRecord, ...]:
        return self._saved_projections.snapshot_refs(path, refs)

    def restore_saved_projections(
        self,
        records: Iterable[SavedProjectionRecord],
    ) -> int:
        return self._saved_projections.restore(records)

    def delete_saved_projection_refs(
        self,
        path: Path,
        refs: Iterable[EntryRef],
    ) -> int:
        return self._saved_projections.delete_refs(path, refs)

    def delete_saved_projections(
        self,
        path: Path,
        language: Language,
        word_keys: Iterable[str],
    ) -> int:
        return self._saved_projections.delete_keys(path, language, word_keys)

    def shift_saved_projections_after_delete(
        self,
        path: Path,
        row_numbers: Iterable[int],
    ) -> int:
        return self._saved_projections.shift_after_delete(path, row_numbers)

    def shift_saved_projections_for_insert(
        self,
        path: Path,
        row_numbers: Iterable[int],
    ) -> int:
        return self._saved_projections.shift_for_insert(path, row_numbers)

    def enqueue_anki_delete(
        self,
        path: Path,
        words: list[str],
        language: Language,
    ) -> str:
        return self._anki_delete_outbox.enqueue(path, words, language)

    def get_anki_delete_operation(
        self,
        operation_id: str,
    ) -> AnkiDeleteOperation | None:
        return self._anki_delete_outbox.get(operation_id)

    def pending_anki_deletes(self, limit: int = 100) -> list[AnkiDeleteOperation]:
        return self._anki_delete_outbox.pending(limit)

    def cancel_anki_delete(self, operation_id: str) -> bool:
        return self._anki_delete_outbox.cancel(operation_id)

    def complete_anki_delete(self, operation_id: str) -> bool:
        return self._anki_delete_outbox.complete(operation_id)

    def fail_anki_delete(self, operation_id: str, error: str) -> bool:
        return self._anki_delete_outbox.fail(operation_id, error)

    def delete_recent_entries(self, language: Language, word_keys: Iterable[str]) -> int:
        return self._recent.delete_recent_entries(language, word_keys)

    def clear_recent(self) -> None:
        self._recent.clear_recent()

    def snapshot_recent_lookups(self) -> list[RecentRow]:
        return self._recent.snapshot_recent_lookups()

    def restore_recent_lookups(self, rows: Iterable[RecentRow]) -> int:
        return self._recent.restore_recent_lookups(rows)

    def set_state(self, key: str, value: str) -> None:
        self._state.set_state(key, value)

    def get_state(self, key: str) -> str | None:
        return self._state.get_state(key)

    def remember_lookup(
        self,
        word: str,
        language: Language,
        entry_word: str | None = None,
    ) -> None:
        self._recent.remember_lookup(word, language, entry_word)

    def recent(self, limit: int = 20) -> list[RecentRow]:
        return self._recent.recent(limit)

    def recent_with_entries(self, limit: int = 20) -> list[RecentEntryRow]:
        return self._recent_entries.recent_with_entries(limit)


class _LockedConnection:
    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def __enter__(self) -> sqlite3.Connection:
        self._lock.acquire()
        self._conn.__enter__()
        return self._conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            return self._conn.__exit__(exc_type, exc, traceback)
        finally:
            self._lock.release()
