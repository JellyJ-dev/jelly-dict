from __future__ import annotations

from app.services.anki_sync_service import AnkiSyncService
from app.storage.settings_store import Settings


class _FakeClient:
    def __init__(self) -> None:
        self.find_calls: list[tuple[str, str, str]] = []
        self.deleted: list[int] = []

    def find_notes_by_field(self, deck_prefix: str, field: str, value: str) -> list[int]:
        self.find_calls.append((deck_prefix, field, value))
        return [101] if value == "apple" else []

    def delete_notes(self, note_ids: list[int]) -> int:
        self.deleted.extend(note_ids)
        return len(note_ids)


def test_delete_words_limits_search_to_language_deck(monkeypatch):
    service = AnkiSyncService(
        Settings(
            ankiconnect_enabled=True,
            ankiconnect_deck_prefix="JellyDict",
        )
    )
    client = _FakeClient()
    monkeypatch.setattr(service, "_client", lambda: client)

    deleted, errors = service.delete_words(["apple"], "en")

    assert deleted == 1
    assert errors == []
    assert client.find_calls == [("JellyDict::EN", "Word", "apple")]
    assert client.deleted == [101]


def test_delete_words_keeps_base_prefix_when_language_unknown(monkeypatch):
    service = AnkiSyncService(
        Settings(
            ankiconnect_enabled=True,
            ankiconnect_deck_prefix="JellyDict",
        )
    )
    client = _FakeClient()
    monkeypatch.setattr(service, "_client", lambda: client)

    service.delete_words(["apple"], None)

    assert client.find_calls == [("JellyDict", "Word", "apple")]


def test_delete_words_uses_export_deck_name_when_prefix_is_default(monkeypatch):
    service = AnkiSyncService(
        Settings(
            default_deck_name="MyDeck",
            ankiconnect_enabled=True,
            ankiconnect_deck_prefix="JellyDict",
        )
    )
    client = _FakeClient()
    monkeypatch.setattr(service, "_client", lambda: client)

    service.delete_words(["apple"], "ja")

    assert client.find_calls == [("MyDeck::JA", "Word", "apple")]


def test_delete_words_does_not_duplicate_language_suffix(monkeypatch):
    service = AnkiSyncService(
        Settings(
            ankiconnect_enabled=True,
            ankiconnect_deck_prefix="JellyDict::EN",
        )
    )
    client = _FakeClient()
    monkeypatch.setattr(service, "_client", lambda: client)

    service.delete_words(["apple"], "en")

    assert client.find_calls == [("JellyDict::EN", "Word", "apple")]
