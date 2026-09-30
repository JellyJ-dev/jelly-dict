from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.core.utils import utc_now_str

log = logging.getLogger(__name__)


class AppStateStore:
    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

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
