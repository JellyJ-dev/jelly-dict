from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.core import config
from app.core.models import (
    VocabularyEntry,
)
from app.dictionary.base import DictionaryProvider
from app.dictionary.manual_provider import ManualDictionaryProvider
from app.dictionary.naver_crawler import NaverDictionaryCrawlerProvider
from app.ocr import OcrProvider, build_ocr_provider
from app.services.anki_sync_service import AnkiSyncService
from app.services.export_service import ExportService
from app.services.lookup_service import LookupService
from app.services.save_service import SaveService
from app.storage.cache_store import CacheStore
from app.storage.settings_store import Settings, SettingsStore
from app.ui.controllers.browser_prewarm_controller import BrowserPrewarmController
from app.ui.controllers.export_controller import ExportController
from app.ui.controllers.lookup_suggestion_dialog import confirm_lookup_suggestion
from app.ui.controllers.lookup_queue_controller import LookupQueueController
from app.ui.controllers.ocr_controller import OcrController
from app.ui.controllers.recent_controller import RecentController
from app.ui.controllers.save_controller import SaveController
from app.ui.controllers.saved_words_cache_controller import SavedWordsCacheController
from app.ui.controllers.tts_background_controller import (
    TtsBackgroundController,
    append_tts_pre_generation_job as _append_tts_pre_generation_job,
)
from app.ui.controllers.window_state_controller import WindowStateController
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.developer_tools_dialog import DeveloperToolsDialog
from app.ui.duplicate_dialog import prompt_duplicate
from app.ui.export_options import status_summary as export_status_summary
from app.ui.main_window_ui import build_main_window_menu, build_main_window_ui
from app.ui.settings_view import SettingsDialog
from app.ui.startup_perf import StartupPerf
from app.ui.widgets.transient_status_bar import TransientStatusBar

log = logging.getLogger(__name__)
LAST_VIEW_STATE_KEY = "ui.last_view_mode"
WORDBOOK_SORT_STATE_KEY = "ui.wordbook_sort_option"
WORDBOOK_SORT_OPTIONS = {"최신순", "오래된순", "가나다순"}
MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT = 52


def runtime_status_summary(settings: Settings) -> str:
    excel_en = Path(settings.excel_path_for("en")).expanduser().name
    excel_ja = Path(settings.excel_path_for("ja")).expanduser().name
    provider = "Naver" if settings.provider == "naver_crawler" else "Manual"
    cache = "cache on" if settings.cache_enabled else "cache off"
    return f"EN: {excel_en} · JA: {excel_ja} · {provider} · {cache}"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._startup_perf = StartupPerf()
        self._app_event_filter_installed = False
        self._app_state_signal_connected = False
        self._window_state_ctrl = WindowStateController(self)
        self.setWindowTitle("")
        self.setWindowFlag(QtCore.Qt.WindowType.ExpandedClientAreaHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.NoTitleBarBackgroundHint, True)
        self.resize(1180, 820)
        self.setMinimumSize(1020, 700)

        self._settings_store = SettingsStore()
        with self._startup_perf.span("settings_load"):
            self._settings: Settings = self._settings_store.load()
        self._cache = CacheStore()

        with self._startup_perf.span("services"):
            self._provider: DictionaryProvider = self._build_provider()
            self._ocr_provider: OcrProvider = self._build_ocr_provider()
            self._manual_provider = ManualDictionaryProvider()
            self._lookup_service = LookupService(self._provider, self._cache, self._settings)
            self._save_service = SaveService(
                self._settings,
                duplicate_prompt=lambda existing, candidate: prompt_duplicate(
                    existing, candidate, parent=self
                ),
            )
            self._export_service = ExportService(self._settings, self._cache)
            self._anki_sync = AnkiSyncService(self._settings)
            self._export_ctrl = ExportController(
                self, self._settings, self._export_service, self._settings_store
            )
            self._export_ctrl.settingsRequested.connect(self._open_settings)

        self._tts_background_ctrl = TtsBackgroundController(self)
        self._browser_prewarm_ctrl = BrowserPrewarmController(
            self,
            lambda: self._provider,
            self._startup_perf,
        )
        self._wordbook_sort_option = self._cached_wordbook_sort_option()

        with self._startup_perf.span("build_ui"):
            build_main_window_ui(
                self,
                wordbook_sort_option=self._wordbook_sort_option,
                settings=self._settings,
            )
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._app_event_filter_installed = True
            app.applicationStateChanged.connect(self._on_application_state_changed)
            self._app_state_signal_connected = True
        # Controllers that need widgets are built after UI construction.
        self._save_ctrl = SaveController(
            parent=self,
            input_view=self.input_view,
            preview_view=self.preview_view,
            stack=self.stack,
            input_page=self._input_page,
            preview_page=self._preview_page,
            save_service=self._save_service,
            settings_getter=lambda: self._settings,
            status_bar=self.status,
            abort_lookup_queue=lambda: self._lookup_queue_ctrl.abort(),
            schedule_next_lookup=lambda: self._lookup_queue_ctrl.schedule_next(),
            start_saved_words_cache_load=lambda: self._saved_words_cache_ctrl.start(),
            queue_tts_pre_generation=self._queue_tts_pre_generation,
            refresh_recent=lambda remember: self._recent_ctrl.refresh(remember=remember),
            preview_cancelled=lambda: self._lookup_queue_ctrl.preview_cancelled(),
        )
        self._lookup_queue_ctrl = LookupQueueController(
            parent=self,
            input_view=self.input_view,
            status_bar=self.status,
            lookup_service=self._lookup_service,
            manual_provider=self._manual_provider,
            present_entry=self._save_ctrl.present_entry,
            confirm_suggestion=lambda typed, suggestion, detected_language: (
                confirm_lookup_suggestion(self, typed, suggestion, detected_language)
            ),
            return_to_input=self._save_ctrl.return_to_input,
            refresh_recent_if_visible=lambda: self._recent_ctrl.refresh_if_visible(),
        )
        self._ocr_ctrl = OcrController(
            parent=self,
            input_view=self.input_view,
            status_bar=self.status,
            provider=self._ocr_provider,
        )
        self._wordbook_ctrl = WordbookController(
            self,
            self.input_view,
            self._cache,
            self._anki_sync,
            self._settings,
            self.status,
            lookup_service=self._lookup_service,
            queue_tts_pre_generation=self._queue_tts_pre_generation,
            remember_last_view_mode=self._remember_last_view_mode,
        )
        self._recent_ctrl = RecentController(
            self,
            self.input_view,
            self._cache,
            self._wordbook_ctrl,
            self.status,
            self._remember_last_view_mode,
            self.show_undo_toast,
        )
        self._saved_words_cache_ctrl = SavedWordsCacheController(
            self,
            lambda: self._settings,
            self.input_view,
            self._wordbook_ctrl,
            self._recent_ctrl.refresh_if_visible,
            self._startup_perf,
        )
        self._connect_controller_signals()
        build_main_window_menu(self, self._settings)
        with self._startup_perf.span("initial_view"):
            self._restore_last_view_mode()
        self._refresh_status_summary()

        QtCore.QTimer.singleShot(0, lambda: self._startup_perf.mark("first_paint"))
        self._schedule_idle_startup_tasks()

    def _connect_controller_signals(self) -> None:
        self.input_view.submitted.connect(self._lookup_queue_ctrl.submit)
        self.input_view.bulkSubmitted.connect(self._lookup_queue_ctrl.submit_bulk)
        self.input_view.jobCancelRequested.connect(self._lookup_queue_ctrl.cancel_job)
        self.input_view.jobRetryRequested.connect(self._lookup_queue_ctrl.retry_job)
        self.input_view.bulkRetryFailedRequested.connect(self._lookup_queue_ctrl.retry_failed)
        self.input_view.bulkClearFailedRequested.connect(self._lookup_queue_ctrl.clear_failed)
        self.input_view.ocrBatchSubmitted.connect(self._lookup_queue_ctrl.submit_ocr_batch)
        self.input_view.ocrBulkLookupRequested.connect(self._lookup_queue_ctrl.submit_ocr_bulk)
        self.input_view.imageOpenRequested.connect(self._ocr_ctrl.open_image)
        self.input_view.imageDropped.connect(self._ocr_ctrl.start_for_path)
        self.input_view.clipboardImagePasted.connect(self._ocr_ctrl.start_for_clipboard_image)
        self.input_view.ocrCleared.connect(self._ocr_ctrl.cleanup_current_temp)
        self.preview_view.saveRequested.connect(self._save_ctrl.preview_save)
        self.preview_view.cancelled.connect(self._save_ctrl.preview_cancelled)

    def event(self, event: QtCore.QEvent) -> bool:
        self._window_state_ctrl.handle_platform_surface_event(event)
        return super().event(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if self._window_state_ctrl.handle_application_event(watched, event):
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._window_state_ctrl.handle_show_event()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._window_state_ctrl.handle_mouse_double_click(event):
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._window_state_ctrl.handle_mouse_event(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._window_state_ctrl.handle_mouse_event(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._window_state_ctrl.handle_mouse_event(event):
            return
        super().mouseReleaseEvent(event)

    @QtCore.Slot(QtCore.Qt.ApplicationState)
    def _on_application_state_changed(self, state: QtCore.Qt.ApplicationState) -> None:
        self._window_state_ctrl.on_application_state_changed(state)

    def _hide_main_window(self) -> None:
        self._window_state_ctrl.hide_main_window()

    def _restore_hidden_main_window(self) -> None:
        self._window_state_ctrl.restore_hidden_main_window()

    # ---------- helpers --------------------------------------------

    def _schedule_idle_startup_tasks(self) -> None:
        platform = QtWidgets.QApplication.platformName().lower()
        if platform not in {"offscreen", "minimal"}:
            QtCore.QTimer.singleShot(300, self._saved_words_cache_ctrl.start)
        QtCore.QTimer.singleShot(1200, self._cleanup_ocr_temp_dir_idle)

    def _cleanup_ocr_temp_dir_idle(self) -> None:
        with self._startup_perf.span("ocr_temp_cleanup"):
            self._ocr_ctrl.cleanup_temp_dir_idle()

    def _build_provider(self) -> DictionaryProvider:
        if self._settings.provider == "naver_crawler":
            crawler = NaverDictionaryCrawlerProvider()
            crawler.client.update_delay(self._settings.request_delay_seconds)
            return crawler
        return ManualDictionaryProvider()

    def _cached_wordbook_sort_option(self) -> str:
        option = self._cache.get_state(WORDBOOK_SORT_STATE_KEY)
        return option if option in WORDBOOK_SORT_OPTIONS else "최신순"

    def _restore_last_view_mode(self) -> None:
        mode = self._cache.get_state(LAST_VIEW_STATE_KEY)
        if mode in ("en", "ja"):
            self._show_wordbook_inline(mode, remember=False)
            return
        self._recent_ctrl.refresh(remember=False)

    def _remember_last_view_mode(self, mode: str) -> None:
        if mode in ("recent", "en", "ja"):
            self._cache.set_state(LAST_VIEW_STATE_KEY, mode)

    def _remember_wordbook_sort_option(self, option: str) -> None:
        if option in WORDBOOK_SORT_OPTIONS:
            self._cache.set_state(WORDBOOK_SORT_STATE_KEY, option)

    def _build_ocr_provider(self) -> OcrProvider:
        try:
            return build_ocr_provider(self._settings.ocr_provider, self._settings)
        except Exception as exc:
            log.warning("ocr provider fallback to apple_vision: %s", exc)
            return build_ocr_provider("apple_vision", self._settings)

    def _on_ocr_provider_changed(self, name: str) -> None:
        self._settings = self._settings_store.update(ocr_provider=name)
        self._ocr_provider = self._build_ocr_provider()
        self._ocr_ctrl.update_provider(self._ocr_provider)
        self.input_view.set_ocr_provider_label(name)

    def _refresh_status_summary(self) -> None:
        self.input_view.set_status_summary(runtime_status_summary(self._settings))

    def show_undo_toast(self, message: str, undo_callback) -> None:
        self.undo_toast.show_message(message, undo_callback, duration_ms=3000)

    @QtCore.Slot(str)
    def _on_wordbook_sort_changed(self, option: str) -> None:
        self._wordbook_sort_option = option
        self._remember_wordbook_sort_option(option)
        current_mode = self.input_view._list_mode
        if current_mode in ("en", "ja"):
            self._wordbook_ctrl.show_inline(current_mode, option)
            self._remember_last_view_mode(current_mode)

    # ---------- toggles / settings --------------------------------

    @QtCore.Slot(bool)
    def _on_preview_toggle(self, checked: bool) -> None:
        self._settings = self._settings_store.update(show_preview=checked)
        if self.preview_toggle_action.isChecked() != checked:
            self.preview_toggle_action.setChecked(checked)
        self._refresh_status_summary()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._settings_store, self, initial_settings=self._settings)
        dlg.settingsChanged.connect(self._apply_settings)
        dlg.exec()

    @QtCore.Slot(Settings)
    def _apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr_provider = self._build_ocr_provider()
        self._ocr_ctrl.update_provider(self._ocr_provider)
        self.preview_toggle_action.setChecked(settings.show_preview)
        self._lookup_service = LookupService(self._provider, self._cache, settings)
        self._lookup_queue_ctrl.update_lookup_service(self._lookup_service)
        self._save_service = SaveService(
            settings,
            duplicate_prompt=lambda existing, candidate: prompt_duplicate(
                existing, candidate, parent=self
            ),
        )
        self._save_ctrl.update_save_service(self._save_service)
        self._anki_sync = AnkiSyncService(settings)
        self._export_service = ExportService(settings, self._cache)
        self._export_ctrl.update_settings(settings, self._export_service)
        self._wordbook_ctrl.update_settings(settings, self._anki_sync, self._lookup_service)
        self._saved_words_cache_ctrl.start()
        if isinstance(self._provider, NaverDictionaryCrawlerProvider):
            self._provider.client.update_delay(settings.request_delay_seconds)
        self._refresh_status_summary()
        self.status.showMessage("설정 저장됨")

    def _clear_cache(self) -> None:
        try:
            self._cache.clear()
            QtWidgets.QMessageBox.information(self, "캐시", "캐시를 비웠습니다.")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "캐시", f"실패: {exc}")

    def _open_word_list(self, language: str = "en") -> None:
        if language == "recent":
            self._recent_ctrl.refresh(remember=True)
            return
        self._show_wordbook_inline(language)

    def _show_wordbook_inline(self, language: str, *, remember: bool = True) -> None:
        self._wordbook_ctrl.show_inline(language, self._wordbook_sort_option)
        self.input_view.set_anki_export_status(
            export_status_summary(self._settings, language)
        )
        if remember:
            self._remember_last_view_mode(language)

    @QtCore.Slot(str, object)
    def _delete_wordbook_entries(self, language: str, words_obj: object) -> None:
        self._wordbook_ctrl.delete_entries(language, words_obj)

    @QtCore.Slot(str, str)
    def _edit_wordbook_entry(self, language: str, word: str) -> None:
        self._wordbook_ctrl.edit_entry(language, word)

    def _queue_tts_pre_generation(self, entry: VocabularyEntry) -> None:
        self._tts_background_ctrl.queue_entry(self._settings, entry)

    def _open_word_list_dialog(self, language: str = "en") -> None:
        from app.ui.word_list_view import WordListDialog

        dlg = WordListDialog(
            excel_path_for=self._settings.excel_path_for,
            cache_clear=self._cache_clear_keys,
            anki_sync=self._anki_sync,
            language=language,
            parent=self,
        )
        dlg.deleted.connect(self._on_words_deleted)
        dlg.exec()
        self._recent_ctrl.refresh_if_visible()

    @QtCore.Slot(str, str)
    def _open_recent_entry_detail(self, word: str, language: str) -> None:
        self._wordbook_ctrl.open_recent_detail(word, language)

    def _cache_clear_keys(self, language: str, word_keys: set[str]) -> None:
        """Drop deleted words from the SQLite cache so they don't return
        as 'cached' on the next lookup. Used by WordListDialog."""
        try:
            self._cache.delete_entries(language, word_keys)  # type: ignore[arg-type]
        except Exception as exc:
            log.warning("cache delete failed: %s", exc)
        try:
            delete_recent = getattr(self._cache, "delete_recent_entries", None)
            if callable(delete_recent):
                delete_recent(language, word_keys)  # type: ignore[arg-type]
        except Exception as exc:
            log.warning("recent cache delete failed: %s", exc)

    @QtCore.Slot(str, int)
    def _on_words_deleted(self, language: str, count: int) -> None:
        self._saved_words_cache_ctrl.start()
        self._recent_ctrl.refresh_if_visible()
        self.status.showMessage(f"{language} {count}개 삭제됨 (Excel)")

    def _open_developer_tools(self) -> None:
        dlg = DeveloperToolsDialog(self)
        dlg.exec()

    # ---------- export --------------------------------------------

    def _export_tsv(self, language: str) -> None:
        self._export_ctrl.export_tsv(language)

    def _export_apkg(
        self,
        language: str,
        audio_policy: str = "settings",
        force_options: bool = False,
    ) -> None:
        self._export_ctrl.export_apkg(language, audio_policy, force_options)  # type: ignore[arg-type]

    # ---------- lifecycle -----------------------------------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._export_ctrl.is_running():
            QtWidgets.QMessageBox.information(
                self,
                "내보내기 진행 중",
                "Anki 내보내기가 끝난 뒤 종료해주세요.",
            )
            event.ignore()
            return
        if self._lookup_queue_ctrl.is_running() or self._ocr_ctrl.is_running():
            QtWidgets.QMessageBox.information(
                self,
                "작업 진행 중",
                "조회 또는 사진 텍스트 인식이 끝난 뒤 종료해주세요.",
            )
            event.ignore()
            return
        try:
            self._export_ctrl.close()
        except Exception as exc:
            log.warning("export thread cleanup failed: %s", exc)
        try:
            self._lookup_queue_ctrl.close()
        except Exception as exc:
            log.warning("worker thread cleanup failed: %s", exc)
        try:
            self._ocr_ctrl.close()
        except Exception as exc:
            log.warning("ocr thread cleanup failed: %s", exc)
        try:
            if not self._saved_words_cache_ctrl.stop():
                QtWidgets.QMessageBox.information(
                    self,
                    "단어장 확인 중",
                    "저장된 단어 상태 확인이 끝난 뒤 종료해주세요.",
                )
                event.ignore()
                return
        except Exception as exc:
            log.warning("saved words cache cleanup failed: %s", exc)
        self._ocr_ctrl.cleanup_current_temp()
        self._tts_background_ctrl.close()
        self._ocr_ctrl.cleanup_temp_dir_idle()
        try:
            if isinstance(self._provider, NaverDictionaryCrawlerProvider):
                self._provider.close()
        except Exception as exc:
            log.warning("provider close failed: %s", exc)
        app = QtWidgets.QApplication.instance()
        if app is not None and self._app_event_filter_installed:
            app.removeEventFilter(self)
            self._app_event_filter_installed = False
        if app is not None and self._app_state_signal_connected:
            try:
                app.applicationStateChanged.disconnect(self._on_application_state_changed)
            except (RuntimeError, TypeError):
                pass
            self._app_state_signal_connected = False
        super().closeEvent(event)
