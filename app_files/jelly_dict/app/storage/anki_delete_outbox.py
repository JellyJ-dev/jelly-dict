from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.errors import CacheError
from app.core.models import Language
from app.core.utils import utc_now_str

OutboxStatus = Literal["pending", "completed", "cancelled"]


@dataclass(frozen=True)
class AnkiDeleteOperation:
    operation_id: str
    workbook_path: str
    language: Language
    words: tuple[str, ...]
    status: OutboxStatus
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str


class AnkiDeleteOutbox:
    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

    def enqueue(self, path: Path, words: list[str], language: Language) -> str:
        clean_words = tuple(dict.fromkeys(word.strip() for word in words if word.strip()))
        if not clean_words:
            raise ValueError("Anki 삭제 단어가 비어 있습니다.")
        operation_id = uuid.uuid4().hex
        now = utc_now_str()
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO anki_delete_outbox(
                        operation_id, workbook_path, language, words_json, status,
                        attempts, last_error, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, 'pending', 0, NULL, ?, ?)
                    """,
                    (
                        operation_id,
                        str(Path(path).expanduser().resolve(strict=False)),
                        language,
                        json.dumps(clean_words, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return operation_id

    def get(self, operation_id: str) -> AnkiDeleteOperation | None:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT operation_id, workbook_path, language, words_json,
                           status, attempts, last_error, created_at, updated_at
                    FROM anki_delete_outbox
                    WHERE operation_id=?
                    """,
                    (operation_id,),
                ).fetchone()
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return _operation_from_row(row) if row is not None else None

    def pending(self, limit: int = 100) -> list[AnkiDeleteOperation]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT operation_id, workbook_path, language, words_json,
                           status, attempts, last_error, created_at, updated_at
                    FROM anki_delete_outbox
                    WHERE status='pending'
                    ORDER BY id
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return [_operation_from_row(row) for row in rows]

    def cancel(self, operation_id: str) -> bool:
        return self._set_terminal_status(operation_id, "cancelled")

    def complete(self, operation_id: str) -> bool:
        return self._set_terminal_status(operation_id, "completed")

    def fail(self, operation_id: str, error: str) -> bool:
        now = utc_now_str()
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    """
                    UPDATE anki_delete_outbox
                    SET attempts=attempts+1, last_error=?, updated_at=?
                    WHERE operation_id=? AND status='pending'
                    """,
                    (error[:1000], now, operation_id),
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return cursor.rowcount > 0

    def _set_terminal_status(
        self,
        operation_id: str,
        status: Literal["completed", "cancelled"],
    ) -> bool:
        now = utc_now_str()
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    """
                    UPDATE anki_delete_outbox
                    SET status=?, last_error=NULL, updated_at=?
                    WHERE operation_id=? AND status='pending'
                    """,
                    (status, now, operation_id),
                )
        except Exception as exc:
            raise CacheError(str(exc)) from exc
        return cursor.rowcount > 0


def _operation_from_row(row) -> AnkiDeleteOperation:
    words = json.loads(row["words_json"])
    return AnkiDeleteOperation(
        operation_id=row["operation_id"],
        workbook_path=row["workbook_path"],
        language=row["language"],
        words=tuple(str(word) for word in words),
        status=row["status"],
        attempts=int(row["attempts"]),
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
