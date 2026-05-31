"""Bridge between word management UI and AnkiConnect."""
from __future__ import annotations

import logging

from app.anki.ankiconnect_client import AnkiConnectClient, AnkiConnectError
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)


class AnkiSyncService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.ankiconnect_enabled)

    def _client(self) -> AnkiConnectClient:
        return AnkiConnectClient(self._settings.ankiconnect_url)

    def test_connection(self) -> tuple[bool, str]:
        """Returns (ok, message). Safe to call from UI."""
        client = self._client()
        try:
            ok = client.is_available()
        except Exception as exc:
            return False, str(exc)
        return (
            (True, "AnkiConnect 연결 성공.")
            if ok
            else (False, "AnkiConnect 응답이 없습니다.")
        )

    def delete_words(
        self,
        words: list[str],
        language: str | None = None,
    ) -> tuple[int, list[str]]:
        """Delete every Anki note whose 'Word' field matches one of
        `words`. Returns (deleted_count, errors)."""
        if not words or not self.enabled:
            return 0, []
        client = self._client()
        deck_prefix = self._deck_prefix_for(language)
        errors: list[str] = []
        total_deleted = 0
        ids_by_word: dict[int, set[str]] = {}
        for word in words:
            try:
                ids = client.find_notes_by_field(
                    deck_prefix=deck_prefix,
                    field="Word",
                    value=word,
                )
            except AnkiConnectError as exc:
                errors.append(f"{word}: {exc}")
                continue
            for note_id in ids:
                ids_by_word.setdefault(note_id, set()).add(word)
        if not ids_by_word:
            return 0, errors
        try:
            verified_ids = _notes_with_exact_word(client.notes_info(list(ids_by_word)), ids_by_word)
        except AnkiConnectError as exc:
            errors.append(str(exc))
            return 0, errors
        if not verified_ids:
            return 0, errors
        try:
            total_deleted = client.delete_notes(verified_ids)
        except AnkiConnectError as exc:
            errors.append(str(exc))
        return total_deleted, errors

    def _deck_prefix_for(self, language: str | None) -> str:
        default_prefix = Settings().ankiconnect_deck_prefix
        configured = (self._settings.ankiconnect_deck_prefix or "").strip()
        deck_base = (self._settings.default_deck_name or "").strip()
        base = configured
        if not base or base == default_prefix:
            base = deck_base or default_prefix
        if language in ("en", "ja") and base:
            suffix = language.upper()
            parts = base.split("::")
            if parts[-1].upper() in {"EN", "JA"}:
                return "::".join([*parts[:-1], suffix])
            return f"{base}::{suffix}"
        return base


def _notes_with_exact_word(
    notes: list[dict],
    ids_by_word: dict[int, set[str]],
) -> list[int]:
    verified: list[int] = []
    for note in notes:
        note_id = _note_id(note)
        if note_id is None or note_id not in ids_by_word:
            continue
        word = _field_value(note, "Word")
        if word in ids_by_word[note_id]:
            verified.append(note_id)
    return verified


def _note_id(note: dict) -> int | None:
    raw = note.get("noteId", note.get("note_id", note.get("id")))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _field_value(note: dict, field: str) -> str:
    fields = note.get("fields") or {}
    raw = fields.get(field, "")
    if isinstance(raw, dict):
        return str(raw.get("value", "") or "")
    return str(raw or "")
