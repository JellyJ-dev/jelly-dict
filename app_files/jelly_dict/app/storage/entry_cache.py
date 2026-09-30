from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from app.core.cache_policy import (
    CacheSchemaContract,
    cache_contract_is_current,
    cache_contract_matches_lookup,
    cache_spelling_matches,
    entry_cache_contract,
)
from app.core.errors import CacheError
from app.core.models import Language, VocabularyEntry, normalize_word_key
from app.core.utils import utc_now_str
from app.storage.cache_entry_codec import entry_from_cache_json

log = logging.getLogger(__name__)


class EntryCache:
    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

    def get(
        self,
        word: str,
        language: Language,
        *,
        provider_id: str | None = None,
    ) -> VocabularyEntry | None:
        key = normalize_word_key(word, language)
        try:
            with self._conn() as conn:
                row = conn.execute(
                    """
                    SELECT id, entry_json, provider_id, provider_schema_version,
                           parser_id, parser_schema_version
                    FROM entries_cache
                    WHERE language=? AND word_key=?
                    """,
                    (language, key),
                ).fetchone()
                if row and not cache_row_is_current(row, language):
                    conn.execute("DELETE FROM entries_cache WHERE id=?", (row["id"],))
                    row = None
                elif (
                    row
                    and provider_id is not None
                    and not cache_row_matches_provider(
                        row,
                        language,
                        provider_id,
                    )
                ):
                    row = None
        except Exception as exc:  # never let cache failures kill the app
            log.warning("cache get failed: %s", exc)
            return None
        if not row:
            return None
        entry = entry_from_cache_json(row["entry_json"])
        if entry is not None and not cache_spelling_matches(word, entry):
            return None
        if entry is None:
            try:
                with self._conn() as conn:
                    conn.execute("DELETE FROM entries_cache WHERE id=?", (row["id"],))
            except Exception as exc:
                log.warning("corrupt cache row cleanup failed: %s", exc)
        return entry

    def upsert(
        self,
        entry: VocabularyEntry,
        *,
        provider_id: str | None = None,
    ) -> None:
        try:
            with self._conn() as conn:
                now = utc_now_str()
                contract = entry_cache_contract(entry, provider_id)
                conn.execute(
                    """
                    INSERT INTO entries_cache(language, word_key, word_display, entry_json,
                                              source_url, provider_id,
                                              provider_schema_version, parser_id,
                                              parser_schema_version, fetched_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(language, word_key) DO UPDATE SET
                        word_display = excluded.word_display,
                        entry_json   = excluded.entry_json,
                        source_url   = excluded.source_url,
                        provider_id = excluded.provider_id,
                        provider_schema_version = excluded.provider_schema_version,
                        parser_id = excluded.parser_id,
                        parser_schema_version = excluded.parser_schema_version,
                        fetched_at = excluded.fetched_at,
                        updated_at   = excluded.updated_at
                    """,
                    (
                        entry.language,
                        entry.word_key(),
                        entry.word,
                        entry.to_json(),
                        entry.source_url,
                        contract.provider_id,
                        contract.provider_schema_version,
                        contract.parser_id,
                        contract.parser_schema_version,
                        now,
                        now,
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
        keys = [key for key in word_keys if key]
        if not keys:
            return 0
        try:
            with self._conn() as conn:
                conn.executemany(
                    "DELETE FROM entries_cache WHERE language=? AND word_key=?",
                    [(language, key) for key in keys],
                )
        except Exception as exc:
            log.warning("cache delete failed: %s", exc)
            raise CacheError(str(exc)) from exc
        return len(keys)


def _row_contract(row: Any) -> CacheSchemaContract:
    return CacheSchemaContract(
        str(row["provider_id"]),
        int(row["provider_schema_version"]),
        str(row["parser_id"]),
        int(row["parser_schema_version"]),
    )


def cache_row_is_usable(
    row: Any,
    language: Language,
    requested_provider_id: str | None,
) -> bool:
    return cache_row_is_current(row, language) and (
        requested_provider_id is None
        or cache_row_matches_provider(row, language, requested_provider_id)
    )


def cache_row_is_current(row: Any, language: Language) -> bool:
    contract = _row_contract(row)
    return bool(
        cache_contract_is_current(
            provider_id=contract.provider_id,
            provider_schema_version=contract.provider_schema_version,
            parser_id=contract.parser_id,
            parser_schema_version=contract.parser_schema_version,
            language=language,
        )
    )


def cache_row_matches_provider(
    row: Any,
    language: Language,
    requested_provider_id: str,
) -> bool:
    return bool(cache_contract_matches_lookup(_row_contract(row), requested_provider_id, language))
