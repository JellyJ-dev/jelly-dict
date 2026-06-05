from collections.abc import Iterable
from pathlib import Path
import sqlite3
import threading
from types import TracebackType

from app.core.models import Language, VocabularyEntry
from app.storage.app_state_store import AppStateStore
from app.storage.entry_cache import EntryCache
from app.storage.recent_entry_lookup import RecentEntryLookup, RecentEntryRow
from app.storage.recent_store import RecentLookupStore, RecentRow
from app.storage.sqlite_store import open_db


class CacheStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._connection = open_db(self._db_path, check_same_thread=False)
        self._entries = EntryCache(self._conn)
        self._recent = RecentLookupStore(self._conn)
        self._state = AppStateStore(self._conn)
        self._recent_entries = RecentEntryLookup(self._conn, self._recent, self.get)

    def _conn(self):
        return _LockedConnection(self._connection, self._lock)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get(self, word: str, language: Language) -> VocabularyEntry | None:
        return self._entries.get(word, language)

    def upsert(self, entry: VocabularyEntry) -> None:
        self._entries.upsert(entry)

    def clear(self) -> None:
        self._entries.clear()

    def delete_entries(self, language: Language, word_keys: Iterable[str]) -> int:
        return self._entries.delete_entries(language, word_keys)

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
