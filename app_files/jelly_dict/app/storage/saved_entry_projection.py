from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.domain import EntryRef
from app.core.errors import CacheError
from app.core.models import Language, VocabularyEntry, normalize_word_key
from app.core.utils import utc_now_str

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedProjectionRecord:
    workbook_path: str
    ref: EntryRef
    entry_json: str
    updated_at: str

    @property
    def entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.entry_json)


class SavedEntryProjectionStore:
    """Rich saved-entry read models, separate from provider lookup cache."""

    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

    def get(self, path: Path, ref: EntryRef) -> VocabularyEntry | None:
        record = self.get_record(path, ref)
        if record is None:
            return None
        try:
            return record.entry
        except Exception as exc:
            log.warning("saved projection deserialize failed: %s", exc)
            return None

    def get_record(
        self,
        path: Path,
        ref: EntryRef,
    ) -> SavedProjectionRecord | None:
        workbook_path = _workbook_key(path)
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT workbook_path, language, word_key, row_number,
                           row_identity, entry_json, updated_at
                    FROM saved_entry_projections
                    WHERE workbook_path=? AND row_number=? AND row_identity=?
                    """,
                    (workbook_path, ref.row_number, ref.identity),
                ).fetchone()
        except Exception as exc:
            log.warning("saved projection get failed: %s", exc)
            return None
        return _record_from_row(row) if row is not None else None

    def latest(
        self,
        path: Path,
        word: str,
        language: Language,
    ) -> SavedProjectionRecord | None:
        workbook_path = _workbook_key(path)
        word_key = normalize_word_key(word, language)
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT workbook_path, language, word_key, row_number,
                           row_identity, entry_json, updated_at
                    FROM saved_entry_projections
                    WHERE workbook_path=? AND language=? AND word_key=?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (workbook_path, language, word_key),
                ).fetchone()
        except Exception as exc:
            log.warning("saved projection latest failed: %s", exc)
            return None
        return _record_from_row(row) if row is not None else None

    def upsert(
        self,
        path: Path,
        ref: EntryRef,
        entry: VocabularyEntry,
    ) -> None:
        workbook_path = _workbook_key(path)
        now = utc_now_str()
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    DELETE FROM saved_entry_projections
                    WHERE workbook_path=? AND row_number=?
                    """,
                    (workbook_path, ref.row_number),
                )
                conn.execute(
                    """
                    INSERT INTO saved_entry_projections(
                        workbook_path, language, word_key, row_number,
                        row_identity, entry_json, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workbook_path,
                        ref.language,
                        ref.word_key,
                        ref.row_number,
                        ref.identity,
                        entry.to_json(),
                        now,
                    ),
                )
        except Exception as exc:
            log.warning("saved projection upsert failed: %s", exc)
            raise CacheError(str(exc)) from exc

    def snapshot_refs(
        self,
        path: Path,
        refs: Iterable[EntryRef],
    ) -> tuple[SavedProjectionRecord, ...]:
        records = [self.get_record(path, ref) for ref in refs]
        return tuple(record for record in records if record is not None)

    def restore(self, records: Iterable[SavedProjectionRecord]) -> int:
        restored = 0
        for record in records:
            try:
                self.upsert(
                    Path(record.workbook_path),
                    record.ref,
                    record.entry,
                )
            except Exception as exc:
                log.warning("saved projection restore failed: %s", exc)
                continue
            restored += 1
        return restored

    def delete_refs(self, path: Path, refs: Iterable[EntryRef]) -> int:
        workbook_path = _workbook_key(path)
        identities = [(workbook_path, ref.row_number, ref.identity) for ref in refs]
        if not identities:
            return 0
        try:
            with self._conn() as conn:
                conn.executemany(
                    """
                    DELETE FROM saved_entry_projections
                    WHERE workbook_path=? AND row_number=? AND row_identity=?
                    """,
                    identities,
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return len(identities)

    def delete_keys(
        self,
        path: Path,
        language: Language,
        word_keys: Iterable[str],
    ) -> int:
        workbook_path = _workbook_key(path)
        keys = [key for key in word_keys if key]
        if not keys:
            return 0
        try:
            with self._conn() as conn:
                conn.executemany(
                    """
                    DELETE FROM saved_entry_projections
                    WHERE workbook_path=? AND language=? AND word_key=?
                    """,
                    [(workbook_path, language, key) for key in keys],
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return len(keys)

    def shift_after_delete(self, path: Path, row_numbers: Iterable[int]) -> int:
        deleted = sorted({int(row) for row in row_numbers if int(row) >= 2})
        if not deleted:
            return 0
        return self._remap_rows(
            path,
            lambda old: old - sum(row < old for row in deleted),
        )

    def shift_for_insert(self, path: Path, row_numbers: Iterable[int]) -> int:
        inserted = sorted({int(row) for row in row_numbers if int(row) >= 2})
        if not inserted:
            return 0

        def shifted(old: int) -> int:
            new = old
            for row in inserted:
                if new >= row:
                    new += 1
            return new

        return self._remap_rows(path, shifted)

    def clear(self) -> None:
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM saved_entry_projections")
        except Exception as exc:
            raise CacheError(str(exc)) from exc

    def _remap_rows(self, path: Path, mapper) -> int:
        workbook_path = _workbook_key(path)
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT id, row_number
                    FROM saved_entry_projections
                    WHERE workbook_path=?
                    ORDER BY id
                    """,
                    (workbook_path,),
                ).fetchall()
                if not rows:
                    return 0
                conn.execute(
                    """
                    UPDATE saved_entry_projections
                    SET row_number = -row_number
                    WHERE workbook_path=?
                    """,
                    (workbook_path,),
                )
                conn.executemany(
                    """
                    UPDATE saved_entry_projections SET row_number=? WHERE id=?
                    """,
                    [(mapper(int(row["row_number"])), row["id"]) for row in rows],
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return len(rows)


def _record_from_row(row) -> SavedProjectionRecord:
    return SavedProjectionRecord(
        workbook_path=row["workbook_path"],
        ref=EntryRef(
            language=row["language"],
            word_key=row["word_key"],
            row_number=int(row["row_number"]),
            identity=row["row_identity"],
        ),
        entry_json=row["entry_json"],
        updated_at=row["updated_at"],
    )


def _workbook_key(path: Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
