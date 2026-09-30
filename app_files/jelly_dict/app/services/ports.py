from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

from app.core.domain import (
    EntryPatch,
    EntryRef,
    ExportSourceRow,
    ExportSourceSnapshot,
    LookupResult,
    SavePreparation,
)
from app.core.models import Language, VocabularyEntry


class DictionaryPort(Protocol):
    def lookup(self, word: str, language: Language) -> LookupResult: ...

    def supports(self, language: Language) -> bool: ...

    def close(self) -> None: ...


class LookupSettingsPort(Protocol):
    cache_enabled: bool


class PathSettingsPort(Protocol):
    def excel_path_for(self, language: str) -> str: ...

    def anki_path_for(self, language: str) -> str: ...


class SavePolicySettingsPort(Protocol):
    duplicate_policy: str
    excel_columns: Sequence[str]


class AnkiSettingsPort(Protocol):
    ankiconnect_enabled: bool
    ankiconnect_url: str
    ankiconnect_deck_prefix: str


class UiPreferencesPort(Protocol):
    default_deck_name: str


class TtsRuntimeSettingsPort(Protocol):
    tts_enabled: bool
    tts_play_front: bool
    tts_play_back: bool
    tts_play_examples: bool
    tts_engine_en: str
    tts_engine_ja: str
    tts_voice_en: str
    tts_voice_ja: str
    tts_bitrate: str
    tts_sample_rate: int
    voicevox_url: str
    tts_voicevox_voices: Sequence[str]

    def excel_path_for(self, language: str) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


class WorkbookSnapshotPort(Protocol):
    path: Path
    revision: Any
    rows: tuple[Any, ...]

    def find_ref(self, ref: EntryRef) -> Any | None: ...

    def find_key(self, language: str, word_key: str) -> Any | None: ...


class WorkbookRepositoryPort(Protocol):
    def read_snapshot(self, path: Path) -> WorkbookSnapshotPort: ...

    def commit_patch_with_backup(
        self,
        path: Path,
        expected_revision: Any,
        patches: Sequence[EntryPatch],
        columns: Sequence[str],
        *,
        backup_reason: str,
        refresh_snapshot: bool = True,
    ) -> Any: ...

    def commit_patch_without_snapshot(
        self,
        path: Path,
        expected_revision: Any,
        patches: Sequence[EntryPatch],
        columns: Sequence[str],
        *,
        backup_reason: str | None = None,
    ) -> Any: ...

    def delete_rows(
        self,
        path: Path,
        expected_revision: Any,
        refs: Sequence[EntryRef],
        *,
        create_backup: bool = True,
    ) -> Any: ...

    def delete_matching_rows(
        self,
        path: Path,
        expected_revision: Any,
        language: str,
        word_keys: set[str],
        *,
        create_backup: bool = True,
    ) -> Any: ...

    def restore_rows(
        self,
        path: Path,
        expected_revision: Any,
        rows: Sequence[Any],
    ) -> Any: ...


class SaveWriteOutcomePort(Protocol):
    action: str
    entry: VocabularyEntry
    backup_path: Path | None
    entry_ref: EntryRef | None
    revision: Any


SaveResolver = Callable[
    [VocabularyEntry | None, VocabularyEntry],
    tuple[str, VocabularyEntry],
]


class WorkbookSavePort(Protocol):
    def prepare_save(
        self,
        path: Path,
        entry: VocabularyEntry,
    ) -> SavePreparation: ...

    def commit_prepared(
        self,
        preparation: SavePreparation,
        action: str,
        entry: VocabularyEntry,
        columns: list[str],
        *,
        backup_on_overwrite: bool = False,
    ) -> SaveWriteOutcomePort: ...

    def save_with_resolver(
        self,
        path: Path,
        entry: VocabularyEntry,
        columns: list[str],
        resolver: SaveResolver,
        *,
        backup_on_overwrite: bool = False,
    ) -> SaveWriteOutcomePort: ...


class LookupCachePort(Protocol):
    def get(
        self,
        word: str,
        language: Language,
        *,
        provider_id: str | None = None,
    ) -> VocabularyEntry | None: ...

    def upsert(
        self,
        entry: VocabularyEntry,
        *,
        provider_id: str | None = None,
    ) -> None: ...

    def delete_entries(
        self,
        language: Language,
        word_keys: Iterable[str],
    ) -> int: ...

    def remember_lookup(
        self,
        word: str,
        language: Language,
        entry_word: str | None = None,
    ) -> None: ...


class ExportCachePort(LookupCachePort, Protocol):
    def get_saved_projection(
        self,
        path: Path,
        ref: EntryRef,
    ) -> VocabularyEntry | None: ...

    def get_many(
        self,
        keys: list[tuple[str, Language]],
        *,
        workbook_path: Path | None = None,
        refs: list[EntryRef | None] | None = None,
    ) -> list[VocabularyEntry | None]: ...


class ExportSourcePort(Protocol):
    def read_rows(self, path: Path, language: str) -> list[ExportSourceRow]: ...

    def prepare_snapshot(
        self,
        path: Path,
        language: str,
    ) -> ExportSourceSnapshot: ...


class ExportWriterPort(Protocol):
    def export_tsv(
        self,
        output_path: Path,
        entries: list[VocabularyEntry],
    ) -> int: ...


class TtsProviderInfoPort(Protocol):
    available: bool
    display_name: str
    voices_en: tuple[str, ...]
    voices_ja: tuple[str, ...]


class ExportCapabilitiesPort(Protocol):
    def genanki_available(self) -> bool: ...

    def tts_provider_info(self, engine: str) -> TtsProviderInfoPort: ...

    def tts_provider_capabilities(self, engine: str) -> Any: ...

    def voicevox_running(self, url: str, timeout: float) -> bool: ...

    def export_apkg(
        self,
        output_path: Path,
        entries: list[VocabularyEntry],
        deck_name: str,
        *,
        settings: TtsRuntimeSettingsPort,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int: ...


class AppStatePort(Protocol):
    def set_state(self, key: str, value: str) -> None: ...

    def get_state(self, key: str) -> str | None: ...


class AnkiSyncPort(Protocol):
    @property
    def enabled(self) -> bool: ...

    def delete_words(
        self,
        words: list[str],
        language: str | None = None,
    ) -> tuple[int, list[str]]: ...


class AnkiClientPort(Protocol):
    def is_available(self) -> bool: ...

    def find_notes_by_field(
        self,
        deck_prefix: str,
        field: str,
        value: str,
    ) -> list[int]: ...

    def find_notes_in_deck(self, deck_prefix: str) -> list[int]: ...

    def notes_info(self, note_ids: list[int]) -> list[dict[str, Any]]: ...

    def delete_notes(self, note_ids: list[int]) -> int: ...


class AnkiClientFactory(Protocol):
    def __call__(self, url: str) -> AnkiClientPort: ...


class TtsPort(Protocol):
    def generate_entry_audio(self, entry: VocabularyEntry) -> int: ...

    def close(self) -> None: ...


class Clock(Protocol):
    def now(self) -> str: ...
