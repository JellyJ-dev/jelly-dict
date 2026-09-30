from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.core import config
from app.core.cache_policy import (
    CACHE_DATABASE_SCHEMA_VERSION,
    cache_contract_is_current,
)
from app.core.diagnostics import diagnostic_operation

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    word_key TEXT NOT NULL,
    word_display TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    source_url TEXT,
    provider_id TEXT NOT NULL,
    provider_schema_version INTEGER NOT NULL,
    parser_id TEXT NOT NULL,
    parser_schema_version INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(language, word_key)
);

CREATE TABLE IF NOT EXISTS recent_lookups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    word TEXT NOT NULL,
    entry_word TEXT,
    looked_up_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recent_time ON recent_lookups(looked_up_at);
CREATE INDEX IF NOT EXISTS idx_recent_lang_word ON recent_lookups(language, word);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_entry_projections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_path TEXT NOT NULL,
    language TEXT NOT NULL,
    word_key TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    row_identity TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workbook_path, row_number, row_identity)
);

CREATE INDEX IF NOT EXISTS idx_saved_projection_key
ON saved_entry_projections(workbook_path, language, word_key, id DESC);

CREATE TABLE IF NOT EXISTS anki_delete_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE,
    workbook_path TEXT NOT NULL,
    language TEXT NOT NULL,
    words_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anki_delete_outbox_pending
ON anki_delete_outbox(status, id);

"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns / indexes introduced in later versions."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(recent_lookups)")}
    if "entry_word" not in cols:
        conn.execute("ALTER TABLE recent_lookups ADD COLUMN entry_word TEXT")
    # Composite index for the GROUP BY (language, word) used by recent().
    # Idempotent CREATE — safe to call on every open.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recent_lang_word ON recent_lookups(language, word)"
    )
    entry_columns = {row[1] for row in conn.execute("PRAGMA table_info(entries_cache)")}
    additions = {
        "provider_id": "TEXT NOT NULL DEFAULT 'legacy'",
        "provider_schema_version": "INTEGER NOT NULL DEFAULT 0",
        "parser_id": "TEXT NOT NULL DEFAULT 'legacy'",
        "parser_schema_version": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, declaration in additions.items():
        if name not in entry_columns:
            conn.execute(f"ALTER TABLE entries_cache ADD COLUMN {name} {declaration}")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_entries_cache_schema
        ON entries_cache(provider_id, parser_id, provider_schema_version, parser_schema_version)
        """
    )
    _invalidate_stale_entry_cache(conn)
    conn.execute(f"PRAGMA user_version = {CACHE_DATABASE_SCHEMA_VERSION}")


def _invalidate_stale_entry_cache(conn: sqlite3.Connection) -> int:
    with diagnostic_operation("cache_migration") as diagnostic:
        stale_ids: list[int] = []
        rows = conn.execute(
            """
            SELECT id, language, provider_id, provider_schema_version,
                   parser_id, parser_schema_version
            FROM entries_cache
            """
        ).fetchall()
        for row in rows:
            language = row["language"]
            if language not in {"en", "ja"} or not cache_contract_is_current(
                provider_id=str(row["provider_id"]),
                provider_schema_version=int(row["provider_schema_version"]),
                parser_id=str(row["parser_id"]),
                parser_schema_version=int(row["parser_schema_version"]),
                language=language,
            ):
                stale_ids.append(int(row["id"]))
        if stale_ids:
            conn.executemany(
                "DELETE FROM entries_cache WHERE id=?",
                [(entry_id,) for entry_id in stale_ids],
            )
            log.info("invalidated %d stale parser cache rows", len(stale_ids))
        diagnostic.finish(
            "empty" if not stale_ids else "success",
            row_count=len(stale_ids),
        )
        return len(stale_ids)


def open_db(
    path: Path | None = None,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    path = path or config.cache_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    database_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if database_version > CACHE_DATABASE_SCHEMA_VERSION:
        log.warning(
            "cache database schema %d is newer than supported schema %d; leaving it untouched",
            database_version,
            CACHE_DATABASE_SCHEMA_VERSION,
        )
        return conn
    conn.executescript(SCHEMA)
    with conn:
        _migrate(conn)
    return conn
