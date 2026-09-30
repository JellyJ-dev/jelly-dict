from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from app.app_container import AppContainer
from app.core import config
from app.core.models import (
    VocabularyEntry,
)
from app.core.settings import AppSettings
from app.providers import get_provider_registry
from app.storage.settings_store import SettingsStore
from app.ui.controller_bundle import build_main_window_controllers
from app.ui.controllers.tts_background_controller import (
    append_tts_pre_generation_job as _append_tts_pre_generation_job,
)
from app.ui.controllers.window_state_controller import WindowStateController
from app.ui.duplicate_dialog import prompt_duplicate
from app.ui.export_options import status_summary as export_status_summary
from app.ui.main_window_ui import build_main_window_menu, build_main_window_ui
from app.ui.startup_perf import StartupPerf
from app.ui.widgets.transient_status_bar import TransientStatusBar

log = logging.getLogger(__name__)
if TYPE_CHECKING:
    from app.services.save_service import SaveOutcome

LAST_VIEW_STATE_KEY = "ui.last_view_mode"
WORDBOOK_SORT_STATE_KEY = "ui.wordbook_sort_option"
WORDBOOK_SORT_OPTIONS = {"최신순", "오래된순", "가나다순"}
MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT = 52


def runtime_status_summary(settings: AppSettings) -> str:
    excel_en = Path(settings.excel_path_for("en")).expanduser().name
    excel_ja = Path(settings.excel_path_for("ja")).expanduser().name
    descriptor = get_provider_registry().descriptor(
        "dictionary",
        settings.provider,
    )
    provider = descriptor.status_label or descriptor.display_name
    cache = "cache on" if settings.cache_enabled else "cache off"
    return f"EN: {excel_en} · JA: {excel_ja} · {provider} · {cache}"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._startup_perf = StartupPerf()
        self._window_event_filter_targets: list[QtWidgets.QWidget] = []
        self._app_state_signal_connected = False
        self._window_state_ctrl = WindowStateController(self)
        self.setWindowTitle("")
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Enum value .*MaximizeUsingFullscreenGeometryHint.*",
                category=DeprecationWarning,
            )
            self.setWindowFlag(QtCore.Qt.WindowType.ExpandedClientAreaHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.NoTitleBarBackgroundHint, True)
        self.resize(1180, 820)
        self.setMinimumSize(1020, 700)

        self._settings_store = SettingsStore()
        with self._startup_perf.span("settings_load"):
            self._settings: AppSettings = self._settings_store.load()

        with self._startup_perf.span("services"):
            self._container = AppContainer(
                lambda existing, candidate: prompt_duplicate(
                    existing,
                    candidate,
                    parent=self,
                ),
                settings_store=self._settings_store,
                settings=self._settings,
            )
            self._sync_container_state()

        self._wordbook_sort_option = self._cached_wordbook_sort_option()

        with self._startup_perf.span("build_ui"):
            build_main_window_ui(
                self,
                wordbook_sort_option=self._wordbook_sort_option,
                settings=self._settings,
                ocr_provider_id=self._container.effective_ocr_provider_id,
            )
        self._install_window_event_filters()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_application_state_changed)
            self._app_state_signal_connected = True
            app.aboutToQuit.connect(self._close_cache)
            app.aboutToQuit.connect(self._close_tts_broker)
        self._controllers = build_main_window_controllers(
            self,
            self._container,
            self._startup_perf,
        )
        self._install_controller_aliases()
        build_main_window_menu(self, self._settings)
        with self._startup_perf.span("initial_view"):
            self._restore_last_view_mode()
        self._refresh_status_summary()

        QtCore.QTimer.singleShot(0, lambda: self._startup_perf.mark("first_paint"))
        self._schedule_idle_startup_tasks()

    def event(self, event: QtCore.QEvent) -> bool:
        self._window_state_ctrl.handle_platform_surface_event(event)
        return super().event(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if self._window_state_ctrl.handle_window_event(watched, event):
            return True
        return super().eventFilter(watched, event)

    def _install_window_event_filters(self) -> None:
        # Do not install this Python QMainWindow as a QApplication-wide event
        # filter. QApplication filters are also invoked while worker-thread
        # QObjects are being torn down, which permits concurrent calls into
        # the same PySide wrapper. The titlebar gestures only need widgets
        # belonging to this window.
        targets = self.findChildren(QtWidgets.QWidget)
        for target in targets:
            target.installEventFilter(self)
        self._window_event_filter_targets = targets

    def _remove_window_event_filters(self) -> None:
        targets, self._window_event_filter_targets = self._window_event_filter_targets, []
        for target in targets:
            try:
                target.removeEventFilter(self)
            except RuntimeError:
                pass

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

    def _sync_container_state(self) -> None:
        """Publish compatibility aliases from the single runtime container."""
        container = self._container
        self._settings_store = container.settings_store
        self._settings = container.settings
        self._cache = container.cache
        self._provider = container.provider
        self._ocr_provider = container.ocr_provider
        self._manual_provider = container.manual_provider
        self._lookup_service = container.lookup_service
        self._workbook_save = container.workbook_save
        self._save_service = container.save_service
        self._export_source = container.export_source
        self._export_writer = container.export_writer
        self._export_capabilities = container.export_capabilities
        self._export_service = container.export_service
        self._anki_client_factory = container.anki_client_factory
        self._wordbook_service = container.wordbook_service

    def _install_controller_aliases(self) -> None:
        controllers = self._controllers
        self._tts_background_ctrl = controllers.tts_background
        self._browser_prewarm_ctrl = controllers.browser_prewarm
        self._export_ctrl = controllers.export
        self._save_ctrl = controllers.save
        self._lookup_queue_ctrl = controllers.lookup_queue
        self._ocr_ctrl = controllers.ocr
        self._wordbook_ctrl = controllers.wordbook
        self._recent_ctrl = controllers.recent
        self._saved_words_cache_ctrl = controllers.saved_words_cache

    def _schedule_idle_startup_tasks(self) -> None:
        platform = QtWidgets.QApplication.platformName().lower()
        if platform not in {"offscreen", "minimal"}:
            QtCore.QTimer.singleShot(300, self._saved_words_cache_ctrl.start)
            QtCore.QTimer.singleShot(
                3500,
                self._wordbook_ctrl.retry_pending_anki_deletes,
            )
        QtCore.QTimer.singleShot(1200, self._cleanup_ocr_temp_dir_idle)

    def _cleanup_ocr_temp_dir_idle(self) -> None:
        with self._startup_perf.span("ocr_temp_cleanup"):
            self._ocr_ctrl.cleanup_temp_dir_idle()

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

    def _on_ocr_provider_changed(self, name: str) -> None:
        self._container.update_settings(ocr_provider=name)
        self._sync_container_state()
        self.input_view.set_ocr_provider_label(self._container.effective_ocr_provider_id)

    def _refresh_status_summary(self) -> None:
        self.input_view.set_status_summary(runtime_status_summary(self._settings))

    def show_undo_toast(
        self,
        message: str,
        undo_callback,
        expire_callback=None,
    ) -> None:
        self.undo_toast.show_message(
            message,
            undo_callback,
            duration_ms=3000,
            expire_callback=expire_callback,
        )

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
        self._container.update_settings(show_preview=checked)
        self._sync_container_state()
        if self.preview_toggle_action.isChecked() != checked:
            self.preview_toggle_action.setChecked(checked)
        self._refresh_status_summary()

    def _open_settings(self) -> None:
        from app.ui.settings_view import SettingsDialog

        dlg = SettingsDialog(
            self._settings_store,
            self,
            initial_settings=self._settings,
            settings_commit=self._commit_settings,
        )
        dlg.exec()

    @QtCore.Slot(object)
    def _apply_settings(self, settings: object) -> None:
        if not isinstance(settings, AppSettings):
            return
        self._container.reconfigure(settings)
        self._finish_settings_apply(settings)

    def _commit_settings(self, settings: AppSettings) -> AppSettings:
        committed = self._container.reconfigure_and_save(settings)
        self._finish_settings_apply(committed)
        return committed

    def _finish_settings_apply(self, settings: AppSettings) -> None:
        self._sync_container_state()
        self.input_view.set_ocr_provider_label(self._container.effective_ocr_provider_id)
        self.preview_toggle_action.setChecked(settings.show_preview)
        self._saved_words_cache_ctrl.start()
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
        self.input_view.set_anki_export_status(export_status_summary(self._settings, language))
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

    def _commit_saved_projection(self, outcome: SaveOutcome) -> None:
        if outcome.entry_ref is None:
            return
        self._cache.upsert_saved_projection(
            outcome.path,
            outcome.entry_ref,
            outcome.entry,
        )

    @QtCore.Slot(str, str)
    def _open_recent_entry_detail(self, word: str, language: str) -> None:
        self._wordbook_ctrl.open_recent_detail(word, language)

    def _open_developer_tools(self) -> None:
        from app.ui.developer_tools_dialog import DeveloperToolsDialog

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

    def _close_cache(self) -> None:
        try:
            self._cache.close()
        except Exception as exc:
            log.warning("cache close failed: %s", exc)

    def _close_tts_broker(self) -> None:
        try:
            from app.tts.broker import close_tts_broker

            if not close_tts_broker():
                log.warning("TTS broker did not stop cleanly")
        except Exception as exc:
            log.warning("TTS broker cleanup failed: %s", exc)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._export_ctrl.is_running():
            QtWidgets.QMessageBox.information(
                self,
                "내보내기 진행 중",
                "Anki 내보내기가 끝난 뒤 종료해주세요.",
            )
            event.ignore()
            return
        if (
            self._save_ctrl.is_running()
            or self._lookup_queue_ctrl.is_running()
            or self._ocr_ctrl.is_running()
            or self._wordbook_ctrl.is_running()
        ):
            QtWidgets.QMessageBox.information(
                self,
                "작업 진행 중",
                "조회 또는 사진 텍스트 인식이 끝난 뒤 종료해주세요.",
            )
            event.ignore()
            return
        try:
            self._save_ctrl.close()
        except Exception as exc:
            log.warning("save thread cleanup failed: %s", exc)
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
            self._wordbook_ctrl.close()
        except Exception as exc:
            log.warning("wordbook thread cleanup failed: %s", exc)
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
        self._close_tts_broker()
        try:
            self._browser_prewarm_ctrl.close()
        except Exception as exc:
            log.warning("browser prewarm cleanup failed: %s", exc)
        self._ocr_ctrl.cleanup_temp_dir_idle()
        self._container.close_provider()
        self._remove_window_event_filters()
        app = QtWidgets.QApplication.instance()
        if app is not None and self._app_state_signal_connected:
            try:
                app.applicationStateChanged.disconnect(self._on_application_state_changed)
            except (RuntimeError, TypeError):
                pass
            self._app_state_signal_connected = False
        self._close_cache()
        super().closeEvent(event)
