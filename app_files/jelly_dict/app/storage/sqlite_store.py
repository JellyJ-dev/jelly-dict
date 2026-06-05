from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    language TEXT NOT NULL,
    word_key TEXT NOT NULL,
    word_display TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    source_url TEXT,
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
"""


def _migrate(conn) -> None:
    """Add columns / indexes introduced in later versions."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(recent_lookups)")}
    if "entry_word" not in cols:
        conn.execute("ALTER TABLE recent_lookups ADD COLUMN entry_word TEXT")
    # Composite index for the GROUP BY (language, word) used by recent().
    # Idempotent CREATE — safe to call on every open.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recent_lang_word "
        "ON recent_lookups(language, word)"
    )


def open_db(
    path: Path | None = None,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    path = path or config.cache_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
