"""Application composition root for runtime services and adapters.

The container owns concrete construction and settings reconfiguration.  UI
controllers consume its already-composed services, which keeps ``MainWindow``
focused on the existing widget lifecycle and prevents partially updated
provider/service graphs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.anki.export_adapter import AnkiExportWriter
from app.anki.export_capability_adapter import AnkiExportCapabilities
from app.anki.sync_adapter import AnkiConnectClientFactory
from app.core.duplicate_checker import DuplicateDecision
from app.core.models import VocabularyEntry
from app.core.settings import AppSettings, SettingsDraft, settings_snapshot
from app.dictionary.base import DictionaryProvider
from app.ocr import OcrProvider
from app.providers import get_provider_registry
from app.services.anki_sync_service import AnkiSyncService
from app.services.export_service import ExportService
from app.services.lookup_service import LookupService
from app.services.save_service import SaveService
from app.services.wordbook_service import WordbookService
from app.storage.cache_store import CacheStore
from app.storage.excel_repository import WorkbookRepository
from app.storage.export_source_adapter import OpenpyxlExportSource
from app.storage.settings_store import SettingsStore
from app.storage.workbook_save_adapter import ExcelWorkbookSaveAdapter

log = logging.getLogger(__name__)

DuplicatePrompt = Callable[
    [VocabularyEntry, VocabularyEntry],
    DuplicateDecision,
]


@dataclass(frozen=True)
class _PreparedReconfigure:
    provider: DictionaryProvider
    ocr_provider: OcrProvider
    effective_ocr_provider_id: str
    lookup_service: LookupService
    save_service: SaveService
    export_service: ExportService
    anki_sync: AnkiSyncService


class AppContainer:
    """Own the replaceable runtime dependency graph.

    ``reconfigure`` first builds every replacement object, then publishes the
    new graph and finally closes the retired provider.  A construction failure
    therefore leaves the active graph untouched.
    """

    def __init__(
        self,
        duplicate_prompt: DuplicatePrompt,
        *,
        settings_store: SettingsStore | None = None,
        cache: CacheStore | None = None,
        settings: AppSettings | SettingsDraft | None = None,
    ) -> None:
        self.settings_store = settings_store or SettingsStore()
        self.settings = (
            settings_snapshot(settings) if settings is not None else self.settings_store.load()
        )
        self.cache = cache or CacheStore()
        self._duplicate_prompt = duplicate_prompt
        self._reconfigure_listeners: list[Callable[[AppContainer], None]] = []
        self.provider_registry = get_provider_registry()

        self.manual_provider = self.provider_registry.create(
            "dictionary",
            "manual",
            self.settings,
        )
        self.workbook_repository = WorkbookRepository()
        self.workbook_save = ExcelWorkbookSaveAdapter(self.workbook_repository)
        self.export_source = OpenpyxlExportSource(self.workbook_repository)
        self.export_writer = AnkiExportWriter()
        self.export_capabilities = AnkiExportCapabilities()
        self.anki_client_factory = AnkiConnectClientFactory()

        self.provider = self._create_provider(self.settings)
        (
            self.ocr_provider,
            self.effective_ocr_provider_id,
        ) = self._resolve_ocr_provider(self.settings)
        self.lookup_service = LookupService(
            self.provider,
            self.cache,
            self.settings.lookup,
        )
        self.save_service = self._create_save_service(self.settings)
        self.export_service = ExportService(
            self.settings.paths,
            self.cache,
            self.export_source,
            self.export_writer,
            tts_settings=self.settings.tts_runtime(),
        )
        self.anki_sync = AnkiSyncService(
            self.settings.anki,
            self.anki_client_factory,
            self.settings.ui,
        )
        self.wordbook_service = WordbookService(
            self.settings.paths,
            self.workbook_repository,
            self.cache,
            self.anki_sync,
            self.settings.lookup,
        )

    def current_settings(self) -> AppSettings:
        return self.settings

    def current_provider(self) -> DictionaryProvider:
        return self.provider

    def update_settings(self, **changes) -> AppSettings:
        return self.reconfigure_and_save(self.settings.with_changes(**changes))

    def add_reconfigure_listener(
        self,
        listener: Callable[[AppContainer], None],
    ) -> None:
        self._reconfigure_listeners.append(listener)

    def reconfigure(self, settings: AppSettings | SettingsDraft) -> AppSettings:
        settings = settings_snapshot(settings)
        prepared = self._prepare_reconfigure(settings)
        return self._publish_reconfigure(settings, prepared)

    def reconfigure_and_save(
        self,
        settings: AppSettings | SettingsDraft,
    ) -> AppSettings:
        """Prepare replacements, commit the file, then publish the graph."""
        settings = settings_snapshot(settings)
        prepared = self._prepare_reconfigure(settings)
        try:
            self.settings_store.save(settings)
        except Exception:
            if prepared.provider is not self.provider:
                self._close_provider(prepared.provider)
            raise
        return self._publish_reconfigure(settings, prepared)

    def _prepare_reconfigure(self, settings: AppSettings) -> _PreparedReconfigure:
        old_settings = self.settings
        old_provider = self.provider
        provider_changed = (
            settings.provider != old_settings.provider
            or settings.request_delay_seconds != old_settings.request_delay_seconds
        )
        ocr_changed = settings.ocr_provider != old_settings.ocr_provider
        replacement_provider = self._create_provider(settings) if provider_changed else old_provider
        try:
            if ocr_changed:
                replacement_ocr, effective_ocr_id = self._resolve_ocr_provider(settings)
            else:
                replacement_ocr = self.ocr_provider
                effective_ocr_id = self.effective_ocr_provider_id
            prepared = _PreparedReconfigure(
                provider=replacement_provider,
                ocr_provider=replacement_ocr,
                effective_ocr_provider_id=effective_ocr_id,
                lookup_service=LookupService(
                    replacement_provider,
                    self.cache,
                    settings.lookup,
                ),
                save_service=self._create_save_service(settings),
                export_service=ExportService(
                    settings.paths,
                    self.cache,
                    self.export_source,
                    self.export_writer,
                    tts_settings=settings.tts_runtime(),
                ),
                anki_sync=AnkiSyncService(
                    settings.anki,
                    self.anki_client_factory,
                    settings.ui,
                ),
            )
        except Exception:
            if replacement_provider is not old_provider:
                self._close_provider(replacement_provider)
            raise

        return prepared

    def _publish_reconfigure(
        self,
        settings: AppSettings,
        prepared: _PreparedReconfigure,
    ) -> AppSettings:
        old_provider = self.provider
        self.settings = settings
        self.provider = prepared.provider
        self.ocr_provider = prepared.ocr_provider
        self.effective_ocr_provider_id = prepared.effective_ocr_provider_id
        self.lookup_service = prepared.lookup_service
        self.save_service = prepared.save_service
        self.export_service = prepared.export_service
        self.anki_sync = prepared.anki_sync
        self.wordbook_service.update_settings(
            settings.paths,
            prepared.anki_sync,
            settings.lookup,
        )
        for listener in tuple(self._reconfigure_listeners):
            listener(self)

        if prepared.provider is not old_provider:
            self._close_provider(old_provider)
        return settings

    def close_provider(self) -> None:
        self._close_provider(self.provider)

    def _create_provider(self, settings: AppSettings) -> DictionaryProvider:
        return self.provider_registry.create(
            "dictionary",
            settings.provider,
            settings,
        )  # type: ignore[return-value]

    def _create_ocr_provider(
        self,
        settings: AppSettings,
    ) -> tuple[OcrProvider, str]:
        try:
            provider = self.provider_registry.create(
                "ocr",
                settings.ocr_provider,
                settings,
            )
            return provider, settings.ocr_provider  # type: ignore[return-value]
        except Exception as exc:
            log.warning("ocr provider fallback to apple_vision: %s", exc)
            provider = self.provider_registry.create(
                "ocr",
                "apple_vision",
                settings,
            )
            return provider, "apple_vision"  # type: ignore[return-value]

    def _resolve_ocr_provider(
        self,
        settings: AppSettings,
    ) -> tuple[OcrProvider, str]:
        result = self._create_ocr_provider(settings)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        # Compatibility for tests/plugins overriding the former factory.
        return result, settings.ocr_provider  # type: ignore[return-value]

    def _create_save_service(self, settings: AppSettings) -> SaveService:
        return SaveService(
            settings.paths,
            self.workbook_save,
            duplicate_prompt=self._duplicate_prompt,
            policy_settings=settings.lookup,
        )

    @staticmethod
    def _close_provider(provider: DictionaryProvider) -> None:
        close = getattr(provider, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception as exc:
            log.warning("provider close failed: %s", exc)
