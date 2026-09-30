"""Bridge between word management UI and AnkiConnect."""

from __future__ import annotations

import logging

from app.core.settings import (
    AnkiSettings,
    AppSettings,
    SettingsDraft,
    settings_snapshot,
)
from app.services.ports import (
    AnkiClientFactory,
    AnkiClientPort,
    AnkiSettingsPort,
    UiPreferencesPort,
)

log = logging.getLogger(__name__)
ANKI_BATCH_SIZE = 500
DEFAULT_ANKI_DECK_PREFIX = "JellyDict"


class AnkiSyncService:
    def __init__(
        self,
        settings: AppSettings | SettingsDraft | AnkiSettings,
        client_factory: AnkiClientFactory,
        ui_settings: UiPreferencesPort | None = None,
    ) -> None:
        if ui_settings is None:
            snapshot = settings_snapshot(settings, validate=False)  # type: ignore[arg-type]
            self._settings: AnkiSettingsPort = snapshot.anki
            self._ui_settings: UiPreferencesPort = snapshot.ui
        else:
            self._settings = settings
            self._ui_settings = ui_settings
        self._client_factory = client_factory

    @property
    def enabled(self) -> bool:
        return bool(self._settings.ankiconnect_enabled)

    def _client(self) -> AnkiClientPort:
        return self._client_factory(self._settings.ankiconnect_url)

    def test_connection(self) -> tuple[bool, str]:
        """Returns (ok, message). Safe to call from UI."""
        client = self._client()
        try:
            ok = client.is_available()
        except Exception as exc:
            return False, str(exc)
        return (True, "AnkiConnect 연결 성공.") if ok else (False, "AnkiConnect 응답이 없습니다.")

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
        target_words = {word for word in words if isinstance(word, str) and word}
        if not target_words:
            return 0, []
        try:
            candidate_ids = list(dict.fromkeys(client.find_notes_in_deck(deck_prefix)))
        except Exception as exc:
            return 0, [str(exc)]
        if not candidate_ids:
            return 0, errors
        verified_ids: list[int] = []
        for note_id_chunk in _chunks(candidate_ids, ANKI_BATCH_SIZE):
            try:
                notes = client.notes_info(note_id_chunk)
            except Exception as exc:
                errors.append(str(exc))
                continue
            verified_ids.extend(_notes_with_exact_word(notes, target_words))
        if not verified_ids:
            return 0, errors
        for note_id_chunk in _chunks(verified_ids, ANKI_BATCH_SIZE):
            try:
                total_deleted += client.delete_notes(note_id_chunk)
            except Exception as exc:
                errors.append(str(exc))
        return total_deleted, errors

    def _deck_prefix_for(self, language: str | None) -> str:
        default_prefix = DEFAULT_ANKI_DECK_PREFIX
        configured = (self._settings.ankiconnect_deck_prefix or "").strip()
        deck_base = (self._ui_settings.default_deck_name or "").strip()
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
    target_words: set[str],
) -> list[int]:
    verified: list[int] = []
    for note in notes:
        note_id = _note_id(note)
        if note_id is None:
            continue
        word = _field_value(note, "Word")
        if word in target_words:
            verified.append(note_id)
    return verified


def _chunks(values: list[int], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


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
