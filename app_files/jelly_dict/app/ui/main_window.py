from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from app.core import config
from app.core.models import (
    Language,
    VocabularyEntry,
    first_meaning_hint,
    normalize_word_key,
)
from app.dictionary.base import DictionaryProvider
from app.dictionary.manual_provider import ManualDictionaryProvider
from app.dictionary.naver_crawler import NaverDictionaryCrawlerProvider
from app.ocr import OcrProvider, build_ocr_provider
from app.ocr import temp_files as ocr_temp_files
from app.services.anki_sync_service import AnkiSyncService
from app.services.export_service import ExportService
from app.services.lookup_service import LookupService
from app.services.save_service import SaveService
from app.storage.cache_store import CacheStore
from app.storage.settings_store import Settings, SettingsStore
from app.ui.controllers.export_controller import ExportController
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.developer_tools_dialog import DeveloperToolsDialog
from app.ui.duplicate_dialog import prompt_duplicate
from app.ui.entry_edit_dialog import EntryEditDialog
from app.ui.export_options import status_summary as export_status_summary
from app.ui.entry_detail_dialog import EntryDetailDialog
from app.ui.lookup_worker import LookupWorker
from app.ui.ocr_worker import OcrWorker
from app.ui.preview_editor_view import PreviewEditorView
from app.ui.settings_view import SettingsDialog
from app.ui.startup_perf import StartupPerf
from app.ui.word_input_view import WordInputView
from app.ui.widgets.pill_scrollbar import install_pill_scrollbars
from app.ui.widgets.undo_toast import UndoToast
from app.storage import excel_writer

log = logging.getLogger(__name__)
LAST_VIEW_STATE_KEY = "ui.last_view_mode"
WORDBOOK_SORT_STATE_KEY = "ui.wordbook_sort_option"
WORDBOOK_SORT_OPTIONS = {"최신순", "오래된순", "가나다순"}
MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT = 52
TTS_PREGEN_QUEUE_LIMIT = 64


def runtime_status_summary(settings: Settings) -> str:
    excel_en = Path(settings.excel_path_for("en")).expanduser().name
    excel_ja = Path(settings.excel_path_for("ja")).expanduser().name
    provider = "Naver" if settings.provider == "naver_crawler" else "Manual"
    cache = "cache on" if settings.cache_enabled else "cache off"
    return f"EN: {excel_en} · JA: {excel_ja} · {provider} · {cache}"


def _tts_pre_generation_pipeline_key(settings: Settings) -> tuple[object, ...]:
    return (
        settings.tts_engine_en,
        settings.tts_engine_ja,
        settings.tts_voice_en,
        settings.tts_voice_ja,
        settings.tts_bitrate,
        settings.tts_sample_rate,
        settings.excel_path_for("en"),
        settings.excel_path_for("ja"),
        settings.voicevox_url,
    )


def _tts_pre_generation_entry_key(entry: VocabularyEntry) -> tuple[str, str]:
    return (entry.language, normalize_word_key(entry.word, entry.language))


def _append_tts_pre_generation_job(
    queue: list[tuple[Settings, VocabularyEntry]],
    settings: Settings,
    entry: VocabularyEntry,
    *,
    limit: int = TTS_PREGEN_QUEUE_LIMIT,
) -> None:
    entry_key = _tts_pre_generation_entry_key(entry)
    queue[:] = [
        (queued_settings, queued_entry)
        for queued_settings, queued_entry in queue
        if _tts_pre_generation_entry_key(queued_entry) != entry_key
    ]
    queue.append((settings, entry))
    overflow = len(queue) - max(1, limit)
    if overflow > 0:
        del queue[:overflow]


class LookupJob:
    def __init__(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> None:
        self.id = uuid4().hex
        self.word = word
        self.forced_language = forced_language
        self.force_refresh = force_refresh
        self.status = "pending"  # "pending" | "running" | "failed"


class SavedWordsCacheWorker(QtCore.QObject):
    finished = QtCore.Signal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @QtCore.Slot()
    def run(self) -> None:
        saved: set[tuple[str, str]] = set()
        for lang in ("en", "ja"):
            path = Path(self._settings.excel_path_for(lang))
            if not path.exists():
                continue
            try:
                for entry in excel_writer.list_entries(path):
                    if entry.language == lang and (entry.word or "").strip():
                        saved.add((lang, normalize_word_key(entry.word, lang)))
            except Exception as exc:
                log.warning("saved words cache load failed from %s: %s", path, exc)
        self.finished.emit(saved)


class TransientStatusBar(QtWidgets.QFrame):
    DEFAULT_TIMEOUT_MS = 4000
    FADE_DURATION_MS = 240

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transientStatusBar")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._message = ""
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(0)
        self.message_label = QtWidgets.QLabel("")
        self.message_label.setObjectName("transientStatusMessage")
        self.message_label.setTextFormat(QtCore.Qt.PlainText)
        self.message_label.setMinimumWidth(0)
        self.message_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        layout.addWidget(self.message_label)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._dismiss_timer = QtCore.QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._fade_out)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(self.FADE_DURATION_MS)
        self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade.finished.connect(self._finish_fade_out)
        if parent is not None:
            parent.installEventFilter(self)
        self.hide()

    def showMessage(self, message: str, timeout: int = 0) -> None:  # noqa: N802
        message = (message or "").strip()
        if not message:
            self.clearMessage()
            return
        self._dismiss_timer.stop()
        self._fade.stop()
        self._message = message
        self.message_label.setText(message)
        self.message_label.setToolTip(message)
        self.adjustSize()
        self._place()
        self._opacity.setOpacity(1.0)
        self.show()
        self.raise_()
        self._dismiss_timer.start(timeout if timeout > 0 else self.DEFAULT_TIMEOUT_MS)

    def clearMessage(self) -> None:  # noqa: N802
        self._dismiss_timer.stop()
        self._fade.stop()
        self._message = ""
        self.message_label.setText("")
        self.message_label.setToolTip("")
        self._opacity.setOpacity(0.0)
        self.hide()

    def currentMessage(self) -> str:  # noqa: N802
        return self._message

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.parent() and event.type() == QtCore.QEvent.Resize:
            self._place()
        return super().eventFilter(watched, event)

    def _fade_out(self) -> None:
        if self.isHidden() or not self._message:
            return
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.setDuration(self.FADE_DURATION_MS)
        self._fade.start()

    def _finish_fade_out(self) -> None:
        if self._opacity.opacity() > 0.01:
            return
        self._message = ""
        self.message_label.setText("")
        self.message_label.setToolTip("")
        self._opacity.setOpacity(0.0)
        self.hide()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        hint = self.sizeHint()
        text_width = self.message_label.fontMetrics().horizontalAdvance(self._message)
        width = min(max(hint.width(), text_width + 20, 220), max(220, parent.width() - 24))
        height = max(hint.height(), 28)
        self.resize(width, height)
        self._sync_message_elide()
        self.move(8, max(8, parent.height() - height - 8))

    def _sync_message_elide(self) -> None:
        available = max(40, self.width() - 20)
        self.message_label.setText(
            self.message_label.fontMetrics().elidedText(
                self._message,
                QtCore.Qt.ElideRight,
                available,
            )
        )


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._startup_perf = StartupPerf()
        self._macos_titlebar_chrome_applied = False
        self._app_event_filter_installed = False
        self._app_state_signal_connected = False
        self._titlebar_drag_origin: QtCore.QPoint | None = None
        self._titlebar_drag_window_origin: QtCore.QPoint | None = None
        self._titlebar_zoom_restore_geometry: QtCore.QRect | None = None
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

        self._worker_thread: QtCore.QThread | None = None
        self._current_worker: LookupWorker | None = None
        self._ocr_thread: QtCore.QThread | None = None
        self._ocr_worker: OcrWorker | None = None
        self._saved_words_thread: QtCore.QThread | None = None
        self._saved_words_worker: SavedWordsCacheWorker | None = None
        self._saved_words_started: float | None = None
        self._tts_pregen_lock = threading.Lock()
        self._tts_pregen_queue: list[tuple[Settings, VocabularyEntry]] = []
        self._tts_pregen_active = False
        self._ocr_temp_path: Path | None = None
        self._browser_prewarm_started = False
        self._browser_prewarm_timer = QtCore.QTimer(self)
        self._browser_prewarm_timer.setSingleShot(True)
        self._browser_prewarm_timer.setInterval(900)
        self._browser_prewarm_timer.timeout.connect(self._prewarm_browser)
        self._lookup_queue: list[LookupJob] = []
        self._active_job: LookupJob | None = None
        self._lookup_queue_total = 0
        self._queue_timer = QtCore.QTimer(self)
        self._queue_timer.setSingleShot(True)
        self._queue_timer.setInterval(1000)
        self._queue_timer.timeout.connect(self._start_next_queued_lookup)
        self._wordbook_sort_option = self._cached_wordbook_sort_option()

        with self._startup_perf.span("build_ui"):
            self._build_ui()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._app_event_filter_installed = True
            app.applicationStateChanged.connect(self._on_application_state_changed)
            self._app_state_signal_connected = True
        # Controllers that need widgets (input_view, status bar) must be
        # built after _build_ui so we can pass live references.
        self._wordbook_ctrl = WordbookController(
            self,
            self.input_view,
            self._cache,
            self._anki_sync,
            self._settings,
            self.status,
        )
        self._build_menu()
        with self._startup_perf.span("initial_view"):
            self._restore_last_view_mode()
        self._refresh_status_summary()

        QtCore.QTimer.singleShot(0, lambda: self._startup_perf.mark("first_paint"))
        self._schedule_idle_startup_tasks()

    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.PlatformSurface:
            self._apply_macos_titlebar_chrome()
        return super().event(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        app = QtWidgets.QApplication.instance()
        if watched is app and event.type() == QtCore.QEvent.Type.ApplicationActivate:
            QtCore.QTimer.singleShot(0, self._restore_hidden_main_window)
            return False
        if event.type() == QtCore.QEvent.Type.MouseButtonDblClick and isinstance(
            event,
            QtGui.QMouseEvent,
        ):
            widget = watched if isinstance(watched, QtWidgets.QWidget) else None
            if widget is not None and widget.window() is self:
                window_pos = self.mapFromGlobal(event.globalPosition().toPoint())
                if self._should_handle_titlebar_double_click(event, window_pos):
                    self._clear_titlebar_drag()
                    self._perform_titlebar_zoom()
                    event.accept()
                    return True
        if isinstance(event, QtGui.QMouseEvent):
            widget = watched if isinstance(watched, QtWidgets.QWidget) else None
            if widget is not None and widget.window() is self:
                window_pos = self.mapFromGlobal(event.globalPosition().toPoint())
                if self._handle_titlebar_drag_event(event, window_pos):
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._apply_macos_titlebar_chrome()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._should_handle_titlebar_double_click(event):
            self._clear_titlebar_drag()
            self._perform_titlebar_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._handle_titlebar_drag_event(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._handle_titlebar_drag_event(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._handle_titlebar_drag_event(event):
            return
        super().mouseReleaseEvent(event)

    @QtCore.Slot(QtCore.Qt.ApplicationState)
    def _on_application_state_changed(self, state: QtCore.Qt.ApplicationState) -> None:
        if state == QtCore.Qt.ApplicationState.ApplicationActive:
            QtCore.QTimer.singleShot(0, self._restore_hidden_main_window)

    def _hide_main_window(self) -> None:
        app = QtWidgets.QApplication.instance()
        if (
            sys.platform == "darwin"
            and app is not None
            and app.platformName().lower() == "cocoa"
        ):
            try:
                from AppKit import NSApp

                NSApp.hide_(None)
                return
            except Exception as exc:  # pragma: no cover - depends on macOS app session
                log.info("macOS app hide fallback used: %s", exc)
        self.hide()

    def _restore_hidden_main_window(self) -> None:
        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            self.show()
        if self.isVisible():
            self.raise_()
            self.activateWindow()

    def _should_handle_titlebar_double_click(
        self,
        event: QtGui.QMouseEvent,
        window_pos: QtCore.QPoint | None = None,
    ) -> bool:
        if sys.platform != "darwin" or event.button() != QtCore.Qt.LeftButton:
            return False
        y_pos = window_pos.y() if window_pos is not None else event.position().y()
        return 0 <= y_pos <= MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT

    def _should_handle_titlebar_drag(
        self,
        event: QtGui.QMouseEvent,
        window_pos: QtCore.QPoint | None = None,
    ) -> bool:
        if sys.platform != "darwin" or event.button() != QtCore.Qt.LeftButton:
            return False
        y_pos = window_pos.y() if window_pos is not None else event.position().y()
        return 0 <= y_pos <= MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT

    def _handle_titlebar_drag_event(
        self,
        event: QtGui.QMouseEvent,
        window_pos: QtCore.QPoint | None = None,
    ) -> bool:
        if sys.platform != "darwin":
            return False
        event_type = event.type()
        if event_type == QtCore.QEvent.Type.MouseButtonPress:
            if not self._should_handle_titlebar_drag(event, window_pos):
                self._clear_titlebar_drag()
                return False
            self._titlebar_drag_origin = event.globalPosition().toPoint()
            self._titlebar_drag_window_origin = self.frameGeometry().topLeft()
            return False
        if event_type == QtCore.QEvent.Type.MouseMove:
            if self._titlebar_drag_origin is None:
                return False
            if not (event.buttons() & QtCore.Qt.LeftButton):
                self._clear_titlebar_drag()
                return False
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._titlebar_drag_origin
            if delta.manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return False
            window_handle = self.windowHandle()
            if window_handle is not None and window_handle.startSystemMove():
                self._clear_titlebar_drag()
                event.accept()
                return True
            if self._titlebar_drag_window_origin is not None:
                self.move(self._titlebar_drag_window_origin + delta)
                event.accept()
                return True
        if event_type == QtCore.QEvent.Type.MouseButtonRelease:
            self._clear_titlebar_drag()
            return False
        return False

    def _clear_titlebar_drag(self) -> None:
        self._titlebar_drag_origin = None
        self._titlebar_drag_window_origin = None

    def _perform_titlebar_zoom(self) -> None:
        app = QtWidgets.QApplication.instance()
        if self._restore_titlebar_zoom_geometry():
            return
        if (
            sys.platform == "darwin"
            and app is not None
            and app.platformName().lower() == "cocoa"
        ):
            try:
                import ctypes
                import objc

                ns_view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
                ns_window = ns_view.window()
                if ns_window is not None:
                    if ns_window.isZoomed():
                        ns_window.performZoom_(None)
                        return
                    self._titlebar_zoom_restore_geometry = QtCore.QRect(self.geometry())
                    ns_window.performZoom_(None)
                    return
            except Exception as exc:  # pragma: no cover - depends on macOS window server
                log.info("macOS titlebar zoom fallback used: %s", exc)
        if self.isMaximized():
            self.showNormal()
            return
        self._titlebar_zoom_restore_geometry = QtCore.QRect(self.geometry())
        self.showMaximized()

    def _restore_titlebar_zoom_geometry(self) -> bool:
        restore_geometry = self._titlebar_zoom_restore_geometry
        if restore_geometry is None or restore_geometry.isNull():
            self._titlebar_zoom_restore_geometry = None
            return False
        self._titlebar_zoom_restore_geometry = None
        self.showNormal()
        self.setGeometry(restore_geometry)
        return True

    def _apply_macos_titlebar_chrome(self) -> None:
        if self._macos_titlebar_chrome_applied or sys.platform != "darwin":
            return
        app = QtWidgets.QApplication.instance()
        if app is not None and app.platformName().lower() != "cocoa":
            return
        try:
            import ctypes
            import objc
            from AppKit import (
                NSColor,
                NSMaxYEdge,
                NSTitlebarSeparatorStyleNone,
                NSWindowStyleMaskFullSizeContentView,
                NSWindowTitleHidden,
            )

            ns_view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
            ns_window = ns_view.window()
            if ns_window is None:
                QtCore.QTimer.singleShot(0, self._apply_macos_titlebar_chrome)
                return
            ns_window.setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    27 / 255,
                    27 / 255,
                    26 / 255,
                    1,
                )
            )
            ns_window.setTitleVisibility_(NSWindowTitleHidden)
            ns_window.setTitlebarAppearsTransparent_(True)
            ns_window.setStyleMask_(
                ns_window.styleMask() | NSWindowStyleMaskFullSizeContentView
            )
            ns_window.setTitlebarSeparatorStyle_(NSTitlebarSeparatorStyleNone)
            ns_window.setAutorecalculatesContentBorderThickness_forEdge_(
                False,
                NSMaxYEdge,
            )
            ns_window.setContentBorderThickness_forEdge_(0, NSMaxYEdge)
            ns_window.setMovableByWindowBackground_(True)
            self._macos_titlebar_chrome_applied = True
        except Exception as exc:  # pragma: no cover - depends on macOS window server
            log.info("macOS titlebar chrome update skipped: %s", exc)

    # ---------- UI scaffolding -------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        self.input_view = WordInputView()
        self.input_view.wordbook_sort_btn.setText(self._wordbook_sort_option)
        self.input_view.submitted.connect(self._on_submit)
        self.input_view.bulkSubmitted.connect(self._on_bulk_submit)
        self.input_view.jobCancelRequested.connect(self._on_job_cancel_requested)
        self.input_view.jobRetryRequested.connect(self._on_job_retry_requested)
        self.input_view.bulkRetryFailedRequested.connect(self._on_bulk_retry_failed_requested)
        self.input_view.bulkClearFailedRequested.connect(self._on_bulk_clear_failed_requested)
        self.input_view.wordbookSortChanged.connect(self._on_wordbook_sort_changed)
        self.input_view.wordbookEditRequested.connect(self._edit_wordbook_entry)
        self.input_view.ocrBatchSubmitted.connect(self._on_ocr_batch_submit)
        self.input_view.ocrBulkLookupRequested.connect(self._on_ocr_bulk_submit)
        self.input_view.clearRecentRequested.connect(self._clear_recent)
        self.input_view.openWordListRequested.connect(self._open_word_list)
        self.input_view.openSettingsRequested.connect(self._open_settings)
        self.input_view.recentEntryRequested.connect(self._open_recent_entry_detail)
        self.input_view.wordbookDeleteRequested.connect(self._delete_wordbook_entries)
        self.input_view.wordbookExportRequested.connect(self._export_apkg)
        self.input_view.imageOpenRequested.connect(self._open_image_for_ocr)
        self.input_view.imageDropped.connect(self._start_ocr_for_path)
        self.input_view.clipboardImagePasted.connect(self._start_ocr_for_clipboard_image)
        self.input_view.ocrProviderChanged.connect(self._on_ocr_provider_changed)
        self.input_view.ocrCleared.connect(self._cleanup_current_ocr_temp)
        if hasattr(self.input_view, "prewarmRequested"):
            self.input_view.prewarmRequested.connect(self._schedule_browser_prewarm)
        self.input_view.set_ocr_provider_label(self._settings.ocr_provider)

        input_scroll = QtWidgets.QScrollArea()
        input_scroll.setObjectName("inputScroll")
        input_scroll.setWidgetResizable(True)
        input_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        input_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        input_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        install_pill_scrollbars(input_scroll, horizontal=False)
        input_scroll.setWidget(self.input_view)

        self.preview_view = PreviewEditorView()
        self.preview_view.saveRequested.connect(self._on_preview_save)
        self.preview_view.cancelled.connect(self._on_preview_cancelled)
        preview_scroll = QtWidgets.QScrollArea()
        preview_scroll.setObjectName("previewScroll")
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        preview_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        preview_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        install_pill_scrollbars(preview_scroll)
        preview_scroll.setWidget(self.preview_view)

        self.stack = QtWidgets.QStackedLayout()
        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(self.stack)
        self.stack.addWidget(input_scroll)
        self.stack.addWidget(preview_scroll)
        root.addWidget(wrapper, 1)
        self._input_page = input_scroll
        self._preview_page = preview_scroll

        self._apply_theme()
        self.status = TransientStatusBar(central)
        self.undo_toast = UndoToast(central)
        self.undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.Undo, self)
        self.undo_shortcut.activated.connect(self.undo_toast.trigger_undo)
        self.close_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Close),
            self,
        )
        self.close_shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
        self.close_shortcut.activated.connect(self._hide_main_window)

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("파일")
        for label, lang in [("영어", "en"), ("일본어", "ja")]:
            action_tsv = QtGui.QAction(f"Anki TSV 내보내기 — {label}...", self)
            action_tsv.triggered.connect(lambda _=False, L=lang: self._export_tsv(L))
            file_menu.addAction(action_tsv)
        file_menu.addSeparator()
        for label, lang in [("영어", "en"), ("일본어", "ja")]:
            action_apkg = QtGui.QAction(f"Anki APKG 내보내기 — {label}...", self)
            action_apkg.triggered.connect(lambda _=False, L=lang: self._export_apkg(L))
            file_menu.addAction(action_apkg)

        tools_menu = menu.addMenu("도구")
        self.preview_toggle_action = QtGui.QAction("저장 전 미리보기", self)
        self.preview_toggle_action.setCheckable(True)
        self.preview_toggle_action.setChecked(self._settings.show_preview)
        self.preview_toggle_action.toggled.connect(self._on_preview_toggle)
        tools_menu.addAction(self.preview_toggle_action)
        tools_menu.addSeparator()

        prefs = QtGui.QAction("설정...", self)
        prefs.setShortcut("Ctrl+,")
        prefs.triggered.connect(self._open_settings)
        tools_menu.addAction(prefs)

        clear_cache = QtGui.QAction("캐시 비우기", self)
        clear_cache.triggered.connect(self._clear_cache)
        tools_menu.addAction(clear_cache)

        manage_menu = menu.addMenu("관리")
        manage_en = QtGui.QAction("영어 단어장...", self)
        manage_en.setShortcut("Ctrl+L")
        manage_en.triggered.connect(lambda: self._show_wordbook_inline("en"))
        manage_menu.addAction(manage_en)
        manage_ja = QtGui.QAction("일본어 단어장...", self)
        manage_ja.triggered.connect(lambda: self._show_wordbook_inline("ja"))
        manage_menu.addAction(manage_ja)

        view_menu = menu.addMenu("보기")
        developer_tools = QtGui.QAction("개발자 도구", self)
        developer_tools.setShortcut("Ctrl+Shift+I")
        developer_tools.triggered.connect(self._open_developer_tools)
        view_menu.addAction(developer_tools)

    # ---------- helpers --------------------------------------------

    def _schedule_idle_startup_tasks(self) -> None:
        platform = QtWidgets.QApplication.platformName().lower()
        if platform not in {"offscreen", "minimal"}:
            QtCore.QTimer.singleShot(300, self._start_saved_words_cache_load)
        QtCore.QTimer.singleShot(1200, self._cleanup_ocr_temp_dir_idle)

    def _start_saved_words_cache_load(self) -> None:
        if self._saved_words_thread is not None:
            try:
                if self._saved_words_thread.isRunning():
                    return
            except RuntimeError:
                self._saved_words_thread = None
                self._saved_words_worker = None
        self._saved_words_started = time.perf_counter()
        thread = QtCore.QThread(self)
        worker = SavedWordsCacheWorker(self._settings)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_saved_words_cache_ready)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_saved_words_worker)
        self._saved_words_thread = thread
        self._saved_words_worker = worker
        thread.start()

    @QtCore.Slot()
    def _clear_saved_words_worker(self) -> None:
        self._saved_words_thread = None
        self._saved_words_worker = None

    def _stop_saved_words_cache_load(self) -> bool:
        thread = self._saved_words_thread
        if thread is None:
            return True
        try:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(2000):
                    return False
        except RuntimeError:
            pass
        self._clear_saved_words_worker()
        return True

    @QtCore.Slot(object)
    def _on_saved_words_cache_ready(self, saved_words: object) -> None:
        if isinstance(saved_words, set):
            self._wordbook_ctrl.set_saved_words_cache(saved_words)
            if self.input_view._list_mode == "recent":
                self._refresh_recent(remember=False)
            self._startup_perf.mark("saved_words_cache", start=self._saved_words_started)
        self._saved_words_started = None

    def _cleanup_ocr_temp_dir_idle(self) -> None:
        with self._startup_perf.span("ocr_temp_cleanup"):
            ocr_temp_files.cleanup_temp_dir()

    def _schedule_browser_prewarm(self) -> None:
        if self._browser_prewarm_started:
            return
        self._browser_prewarm_timer.start()

    def _prewarm_browser(self) -> None:
        """Warm Playwright only after real user input.

        macOS can show a crash report if WebKit is launched by a short-lived
        offscreen validation process. Lookup still starts Playwright lazily
        when needed; this path is only an interactive latency optimization.
        """
        if self._browser_prewarm_started:
            return
        platform = QtWidgets.QApplication.platformName().lower()
        if platform in {"offscreen", "minimal"}:
            return
        if not isinstance(self._provider, NaverDictionaryCrawlerProvider):
            return
        self._browser_prewarm_started = True

        def warm():
            try:
                with self._startup_perf.span("playwright_prewarm"):
                    self._provider.client.start()  # type: ignore[union-attr]
                log.info("playwright pre-warmed")
            except Exception as exc:
                log.warning("pre-warm failed: %s", exc)

        threading.Thread(target=warm, name="jelly-dict-prewarm", daemon=True).start()

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
        self._refresh_recent(remember=False)

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
        self.input_view.set_ocr_provider_label(name)

    def _refresh_recent(self, *, remember: bool = False) -> None:
        items: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        # Single-query JOIN: avoids N+1 round-trips per refresh.
        for lang, word, entry_word, _, cached in self._cache.recent_with_entries(40):
            hint = ""
            display = entry_word or word  # prefer the canonical lemma
            if cached is not None:
                hint = first_meaning_hint(cached)
                if cached.word:
                    display = cached.word
            is_saved = self._wordbook_ctrl.is_word_saved(display, lang)
            if cached is None and not is_saved:
                continue
            dedup_key = (lang, display.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            status = "saved" if is_saved else "recent"

            items.append((display, lang, hint, status))
            if len(items) >= 20:
                break
        self.input_view.set_recent(items)
        if remember:
            self._remember_last_view_mode("recent")

    def _refresh_recent_if_visible(self) -> None:
        if self.input_view._list_mode == "recent":
            self._refresh_recent(remember=False)

    def _refresh_lookup_queue_ui(self) -> None:
        jobs_data = []
        if self._active_job is not None:
            jobs_data.append((self._active_job.word, "running", self._active_job.id))
        for job in self._lookup_queue:
            jobs_data.append((job.word, job.status, job.id))
        self.input_view.set_lookup_queue(jobs_data)

    def _refresh_status_summary(self) -> None:
        self.input_view.set_status_summary(runtime_status_summary(self._settings))

    def show_undo_toast(self, message: str, undo_callback) -> None:
        self.undo_toast.show_message(message, undo_callback, duration_ms=3000)

    _THEME_PATH = Path(__file__).resolve().parent / "resources" / "theme.qss"
    _RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources"

    def _apply_theme(self) -> None:
        try:
            qss = self._THEME_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("theme.qss read failed: %s", exc)
            return
        qss = qss.replace(
            "url(resources/",
            f"url({self._RESOURCE_ROOT.as_posix()}/",
        )
        self.setStyleSheet(qss)


    # ---------- lookup flow ----------------------------------------

    @QtCore.Slot(str)
    def _on_job_cancel_requested(self, job_id: str) -> None:
        if self._active_job is not None and self._active_job.id == job_id:
            return

        target_job = None
        for job in self._lookup_queue:
            if job.id == job_id:
                target_job = job
                break

        if target_job is not None:
            self._lookup_queue.remove(target_job)
            self._lookup_queue_total -= 1
            if not self._lookup_queue:
                self._lookup_queue_total = 1 if self._active_job is not None else 0
            self._refresh_lookup_queue_ui()
            self.status.showMessage(f"'{target_job.word}' 대기가 취소되었습니다.")

    def _is_already_queued_or_active(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> bool:
        normalized = word.strip().lower()
        lang_norm = (forced_language or "").strip().lower()
        if self._active_job is not None:
            active_lang = (self._active_job.forced_language or "").strip().lower()
            if (
                self._active_job.word.strip().lower() == normalized
                and active_lang == lang_norm
                and self._active_job.force_refresh == force_refresh
            ):
                return True
        for job in self._lookup_queue:
            job_lang = (job.forced_language or "").strip().lower()
            if (
                job.word.strip().lower() == normalized
                and job_lang == lang_norm
                and job.force_refresh == force_refresh
            ):
                return True
        return False

    @QtCore.Slot(str, str)
    def _on_submit(self, word: str, forced_language: str) -> None:
        word_stripped = word.strip()
        if not word_stripped:
            return
        if self._is_already_queued_or_active(word_stripped, forced_language):
            self.status.showMessage(f"'{word_stripped}' [{forced_language}] 은(는) 이미 대기열에 존재합니다.")
            self.input_view.reset_input()
            return

        job = LookupJob(word_stripped, forced_language)
        self._lookup_queue.append(job)
        self._lookup_queue_total += 1
        self.input_view.reset_input()
        self._refresh_lookup_queue_ui()
        if not self._is_lookup_active():
            self._start_next_queued_lookup()

    @QtCore.Slot(object, str)
    def _on_ocr_batch_submit(self, tokens_obj: object, forced_language: str) -> None:
        tokens = [
            token.strip()
            for token in tokens_obj
            if isinstance(token, str) and token.strip()
        ] if isinstance(tokens_obj, list) else []
        if not tokens:
            return

        added_count, _skipped_count = self._queue_lookup_tokens(tokens, forced_language)
        self.input_view.reset_input()
        self._refresh_lookup_queue_ui()
        if added_count > 0:
            if not self._is_lookup_active():
                self._start_next_queued_lookup()

    @QtCore.Slot(object, str)
    def _on_bulk_submit(self, tokens_obj: object, forced_language: str) -> None:
        tokens = [
            token.strip()
            for token in tokens_obj
            if isinstance(token, str) and token.strip()
        ] if isinstance(tokens_obj, list) else []
        if not tokens:
            return

        added_count, skipped_count = self._queue_lookup_tokens(tokens, forced_language)
        self.input_view.reset_input()
        self._refresh_lookup_queue_ui()
        if added_count > 0:
            self.status.showMessage(
                f"{added_count}개 단어를 대기열에 추가했습니다."
                + (f" ({skipped_count}개 중복 제외)" if skipped_count else "")
            )
            if not self._is_lookup_active():
                self._start_next_queued_lookup()
            return
        self.status.showMessage("추가할 새 단어가 없습니다.")

    def _queue_lookup_tokens(
        self,
        tokens: list[str],
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> tuple[int, int]:
        added_count = 0
        skipped_count = 0
        for token in tokens:
            if self._is_already_queued_or_active(
                token,
                forced_language,
                force_refresh=force_refresh,
            ):
                skipped_count += 1
                continue
            job = LookupJob(token, forced_language, force_refresh=force_refresh)
            self._lookup_queue.append(job)
            self._lookup_queue_total += 1
            added_count += 1
        return added_count, skipped_count

    @QtCore.Slot(list, str)
    def _on_ocr_bulk_submit(self, tokens: list[str], forced_language: str) -> None:
        self._on_ocr_batch_submit(tokens, forced_language)

    def _start_lookup(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> None:
        self.input_view.set_detection_label("")
        self.input_view.set_lookup_busy(True)
        self.status.showMessage(f"{'재조회' if force_refresh else '조회'} 중: {word}…")
        thread = QtCore.QThread(self)
        worker = LookupWorker(
            self._lookup_service,
            word,
            forced_language or None,
            force_refresh=force_refresh,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_lookup_finished)
        worker.failed.connect(self._on_lookup_failed)
        worker.unsupported.connect(self._on_unsupported)
        worker.ambiguous.connect(self._on_ambiguous)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.unsupported.connect(thread.quit)
        worker.ambiguous.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker_thread = thread
        self._current_worker = worker
        thread.start()

    def _is_lookup_running(self) -> bool:
        if self._worker_thread is None:
            return False
        try:
            return self._worker_thread.isRunning()
        except RuntimeError:
            self._worker_thread = None
            self._current_worker = None
            return False

    def _is_lookup_active(self) -> bool:
        return self._is_lookup_running() or self._queue_timer.isActive()

    def _start_next_queued_lookup(self) -> None:
        if self._is_lookup_running():
            return

        # Find first pending job
        pending_idx = -1
        for i, j in enumerate(self._lookup_queue):
            if j.status == "pending":
                pending_idx = i
                break

        if pending_idx == -1:
            self._active_job = None
            self.input_view.set_lookup_busy(False)
            failed_count = sum(1 for j in self._lookup_queue if j.status == "failed")
            if failed_count > 0:
                self.status.showMessage(f"조회 대기 완료 (실패 {failed_count}개 보류 중)")
            else:
                self._lookup_queue_total = 0
                self.status.showMessage("모든 조회가 완료되었습니다.")
            self._refresh_recent_if_visible()
            self._refresh_lookup_queue_ui()
            return

        job = self._lookup_queue.pop(pending_idx)
        self._active_job = job
        job.status = "running"

        pending_count = sum(1 for j in self._lookup_queue if j.status == "pending")
        index = max(1, self._lookup_queue_total - pending_count)
        self.status.showMessage(f"순차 조회 {index}/{self._lookup_queue_total}: {job.word}")
        self._refresh_recent_if_visible()
        self._refresh_lookup_queue_ui()
        self._start_lookup(
            job.word,
            job.forced_language,
            force_refresh=job.force_refresh,
        )

    def _schedule_next_queued_lookup(self) -> None:
        self._active_job = None
        self._refresh_lookup_queue_ui()

        has_pending = any(j.status == "pending" for j in self._lookup_queue)
        if not has_pending:
            failed_count = sum(1 for j in self._lookup_queue if j.status == "failed")
            if failed_count > 0:
                self.status.showMessage(f"조회 대기 완료 (실패 {failed_count}개 보류 중)")
            else:
                self._lookup_queue_total = 0
                self.status.showMessage("모든 조회가 완료되었습니다.")
            self.input_view.set_lookup_busy(False)
            self._refresh_recent_if_visible()
            return

        self._queue_timer.stop()
        self._queue_timer.start()

    def _finish_lookup_queue(self) -> None:
        self._queue_timer.stop()
        self._active_job = None
        self._lookup_queue = []
        self._lookup_queue_total = 0
        self._refresh_lookup_queue_ui()

    def _abort_lookup_queue(self) -> None:
        self._queue_timer.stop()
        self._active_job = None
        self._lookup_queue = []
        self._lookup_queue_total = 0
        self.input_view.set_lookup_busy(False)
        self._refresh_recent_if_visible()
        self._refresh_lookup_queue_ui()

    @QtCore.Slot(object)
    def _on_lookup_finished(self, outcome) -> None:
        job = self._active_job
        self.input_view.set_lookup_busy(False)

        query_word = job.word if job else (self._current_worker._word if self._current_worker else "?")

        self.input_view.set_detection_label(
            f"감지: {outcome.detected_language}"
            + (" (캐시)" if outcome.from_cache else "")
        )
        result = outcome.result
        if result.ok and result.entry is not None:
            if result.suggested_word and not outcome.from_cache:
                accepted = self._confirm_suggestion(
                    typed=query_word,
                    suggestion=result.suggested_word,
                    detected_language=outcome.detected_language,
                )
                if not accepted:
                    self.status.showMessage("입력어와 다른 결과여서 저장하지 않았습니다.")
                    if self._active_job is not None:
                        self._active_job.status = "failed"
                        self._lookup_queue.insert(0, self._active_job)
                        self._active_job = None
                    self._return_to_input()
                    self._refresh_lookup_queue_ui()
                    self._schedule_next_queued_lookup()
                    return
                # User accepted: use the canonical headword instead of typed.
                result.entry.word = result.suggested_word
            self._present_entry(result.entry)
        elif result.status == "parse_failed":
            typed = query_word
            log.warning("lookup parse failed: word=%s language=%s", typed, outcome.detected_language)
            self.status.showMessage(
                f"파싱 실패: {typed} — 페이지 구조 변경 또는 결과 없음. 직접 입력으로 전환합니다."
            )
            entry = self._manual_provider.lookup(
                typed, outcome.detected_language  # type: ignore[arg-type]
            ).entry
            if entry is not None:
                self._present_entry(entry, force_preview=True)
                return
            if self._active_job is not None:
                self._active_job.status = "failed"
                self._lookup_queue.insert(0, self._active_job)
                self._active_job = None
            self._refresh_lookup_queue_ui()
            self._schedule_next_queued_lookup()
        else:
            log.warning(
                "lookup failed: word=%s language=%s status=%s detail=%s",
                query_word,
                outcome.detected_language,
                result.status,
                result.error_detail or "",
            )
            self.status.showMessage(f"조회 실패: {result.status}")
            if self._active_job is not None:
                self._active_job.status = "failed"
                self._lookup_queue.insert(0, self._active_job)
                self._active_job = None
            self._refresh_lookup_queue_ui()
            self._schedule_next_queued_lookup()

    def _present_entry(self, entry: VocabularyEntry, force_preview: bool = False) -> None:
        if self._settings.show_preview or force_preview:
            self.preview_view.set_entry(entry)
            self.stack.setCurrentWidget(self._preview_page)
        else:
            self._save_entry(entry)

    def _save_entry(self, entry: VocabularyEntry) -> None:
        try:
            outcome = self._save_service.save(entry)
        except Exception as exc:
            log.exception("save failed")
            QtWidgets.QMessageBox.critical(self, "저장 실패", str(exc))
            self._abort_lookup_queue()
            return

        self._start_saved_words_cache_load()
        self._queue_tts_pre_generation(outcome.entry)

        message = f"저장됨 ({outcome.status}) → {outcome.path}"
        if outcome.backup_path is not None:
            message += f" · 백업: {outcome.backup_path}"
        self.status.showMessage(message)
        self._return_to_input()
        self._refresh_recent(remember=True)
        self._schedule_next_queued_lookup()

    def _return_to_input(self) -> None:
        self.stack.setCurrentWidget(self._input_page)
        self.input_view.reset_input()

    @QtCore.Slot(VocabularyEntry)
    def _on_preview_save(self, entry: VocabularyEntry) -> None:
        self._save_entry(entry)

    @QtCore.Slot()
    def _on_preview_cancelled(self) -> None:
        if self._active_job is not None:
            # Cancelled preview can be kept or removed; here we treat it as failed/cancelled
            self._active_job.status = "failed"
            self._lookup_queue.insert(0, self._active_job)
            self._active_job = None
        self._return_to_input()
        self._refresh_lookup_queue_ui()
        self._schedule_next_queued_lookup()

    @QtCore.Slot(str)
    def _on_lookup_failed(self, message: str) -> None:
        log.warning("lookup worker failed: %s", message)
        self.status.showMessage(f"오류: {message}")
        if self._active_job is not None:
            self._active_job.status = "failed"
            self._lookup_queue.insert(0, self._active_job)
            self._active_job = None
        self.input_view.set_lookup_busy(False)
        self._refresh_lookup_queue_ui()
        self._schedule_next_queued_lookup()

    @QtCore.Slot(str)
    def _on_unsupported(self, word: str) -> None:
        log.info("unsupported input language: %s", word)
        self.status.showMessage("입력 언어 미지원")
        if self._active_job is not None:
            self._active_job.status = "failed"
            self._lookup_queue.insert(0, self._active_job)
            self._active_job = None
        self.input_view.set_lookup_busy(False)
        self._refresh_lookup_queue_ui()
        self._schedule_next_queued_lookup()

    @QtCore.Slot(str)
    def _on_job_retry_requested(self, job_id: str) -> None:
        found_job = None
        for job in self._lookup_queue:
            if job.id == job_id and job.status == "failed":
                job.status = "pending"
                found_job = job
                break
        if found_job is not None:
            self.status.showMessage(f"'{found_job.word}' 조회를 재시도합니다.")
            self._refresh_lookup_queue_ui()
            if not self._is_lookup_active():
                self._start_next_queued_lookup()

    @QtCore.Slot()
    def _on_bulk_retry_failed_requested(self) -> None:
        count = 0
        for job in self._lookup_queue:
            if job.status == "failed":
                job.status = "pending"
                count += 1
        if count > 0:
            self.status.showMessage(f"실패한 {count}개 단어 조회를 재시도합니다.")
            self._refresh_lookup_queue_ui()
            if not self._is_lookup_active():
                self._start_next_queued_lookup()

    @QtCore.Slot()
    def _on_bulk_clear_failed_requested(self) -> None:
        new_queue = [job for job in self._lookup_queue if job.status != "failed"]
        removed = len(self._lookup_queue) - len(new_queue)
        if removed > 0:
            self._lookup_queue = new_queue
            self._lookup_queue_total -= removed
            if not self._lookup_queue:
                self._lookup_queue_total = 1 if self._active_job is not None else 0
            self.status.showMessage(f"실패한 {removed}개 단어가 대기열에서 제거되었습니다.")
            self._refresh_lookup_queue_ui()

    @QtCore.Slot(str)
    def _on_wordbook_sort_changed(self, option: str) -> None:
        self._wordbook_sort_option = option
        self._remember_wordbook_sort_option(option)
        current_mode = self.input_view._list_mode
        if current_mode in ("en", "ja"):
            self._wordbook_ctrl.show_inline(current_mode, option)
            self._remember_last_view_mode(current_mode)

    @QtCore.Slot(str)
    def _on_ambiguous(self, word: str) -> None:
        self.input_view.set_lookup_busy(False)
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setWindowTitle("언어 선택")
        msg.setText(
            f"'{word}' — 영어와 일본어 문자가 섞여 있습니다.\n"
            "조회할 사전을 선택하세요."
        )
        en_btn = msg.addButton("English", QtWidgets.QMessageBox.AcceptRole)
        ja_btn = msg.addButton("日本語", QtWidgets.QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("취소", QtWidgets.QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is cancel_btn:
            if self._active_job is not None:
                self._active_job.status = "failed"
                self._lookup_queue.insert(0, self._active_job)
                self._active_job = None
            self.status.showMessage("언어 선택이 취소되었습니다.")
            self._refresh_lookup_queue_ui()
            self._schedule_next_queued_lookup()
            return
        forced: Language = "ja" if clicked is ja_btn else "en"
        refresh = self._active_job.force_refresh if self._active_job is not None else False
        self._start_lookup(word, forced, force_refresh=refresh)

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
        self.preview_toggle_action.setChecked(settings.show_preview)
        self._lookup_service = LookupService(self._provider, self._cache, settings)
        self._anki_sync = AnkiSyncService(settings)
        self._export_service = ExportService(settings, self._cache)
        self._export_ctrl.update_settings(settings, self._export_service)
        self._wordbook_ctrl.update_settings(settings, self._anki_sync)
        self._start_saved_words_cache_load()
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
            self._refresh_recent(remember=True)
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
        language = language if language in ("en", "ja") else "en"
        key = normalize_word_key(word, language)  # type: ignore[arg-type]
        path = Path(self._settings.excel_path_for(language))
        entry = excel_writer.find_existing(path, language, key)
        if entry is None:
            self.status.showMessage("수정할 단어를 찾을 수 없습니다.")
            return

        dialog = EntryEditDialog(entry, self)
        state = {"key": key}
        dialog.requeryRequested.connect(
            lambda: self._requery_wordbook_edit_dialog(dialog, language, state)
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        edited = dialog.current_entry()
        edited.language = language  # type: ignore[assignment]
        new_key = self._save_wordbook_edit(language, state["key"], edited)
        if new_key:
            state["key"] = new_key

    def _save_wordbook_edit(
        self,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
        *,
        create_backup: bool = True,
    ) -> str | None:
        if not entry.word.strip():
            self.status.showMessage("단어는 비울 수 없습니다.")
            return None
        path = Path(self._settings.excel_path_for(language))
        try:
            outcome = excel_writer.replace_entry(
                path,
                language,
                original_key,
                entry,
                self._settings.excel_columns,
                create_backup=create_backup,
            )
        except Exception as exc:
            log.exception("wordbook edit save failed")
            QtWidgets.QMessageBox.critical(self, "수정 실패", str(exc))
            return None
        try:
            self._cache.upsert(entry)
        except Exception as exc:
            log.warning("cache upsert after wordbook edit failed: %s", exc)
        self._queue_tts_pre_generation(entry)

        self._refresh_wordbook_after_mutation(language)
        message = f"{entry.word} 수정됨"
        if outcome.backup_path is not None:
            message += f" · 백업: {outcome.backup_path.name}"
        self.status.showMessage(message)
        return normalize_word_key(entry.word, language)  # type: ignore[arg-type]

    def _requery_wordbook_edit_dialog(
        self,
        dialog: EntryEditDialog,
        language: str,
        state: dict[str, str],
    ) -> None:
        current = dialog.current_entry()
        lookup_word = current.word.strip()
        if not lookup_word:
            dialog.show_status("재조회할 단어가 없습니다.")
            return

        path = Path(self._settings.excel_path_for(language))
        original_key = state["key"]
        original_entry = excel_writer.find_existing(path, language, original_key)
        if original_entry is None:
            original_entry = current

        dialog.set_busy(True)
        try:
            excel_writer.delete_entries_with_backup(path, language, {original_key})
            try:
                self._cache.delete_entries(language, {original_key})  # type: ignore[arg-type]
            except Exception as exc:
                log.warning("cache delete before requery failed: %s", exc)

            outcome = self._lookup_service.lookup(
                lookup_word,
                language,  # type: ignore[arg-type]
                force_refresh=True,
            )
            result = outcome.result
            if result.ok and result.entry is not None:
                refreshed = result.entry
                if result.suggested_word:
                    refreshed.word = result.suggested_word
                refreshed.language = language  # type: ignore[assignment]
                refreshed.id = original_entry.id
                refreshed.created_at = original_entry.created_at
                if current.tags:
                    refreshed.tags = list(current.tags)
                if current.memo:
                    refreshed.memo = current.memo
                refreshed.touch()
                new_key = self._save_wordbook_edit(
                    language,
                    original_key,
                    refreshed,
                    create_backup=False,
                )
                if new_key:
                    state["key"] = new_key
                dialog.set_entry(refreshed)
                dialog.show_status("재조회 완료 · 단어장에 반영했습니다.")
                return

            self._restore_wordbook_entry(language, original_key, original_entry)
            dialog.set_entry(original_entry)
            dialog.show_status("재조회 결과가 없어 기존 데이터를 복원했습니다.")
            self.status.showMessage("재조회 결과 없음 · 기존 데이터를 복원했습니다.")
        except Exception as exc:
            log.exception("wordbook requery failed")
            self._restore_wordbook_entry(language, original_key, original_entry)
            dialog.set_entry(original_entry)
            dialog.show_status("재조회 실패 · 기존 데이터를 복원했습니다.")
            self.status.showMessage(f"재조회 실패: {exc}")
        finally:
            dialog.set_busy(False)

    def _restore_wordbook_entry(
        self,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
    ) -> None:
        path = Path(self._settings.excel_path_for(language))
        try:
            excel_writer.replace_entry(
                path,
                language,
                original_key,
                entry,
                self._settings.excel_columns,
                create_backup=False,
            )
            self._cache.upsert(entry)
            self._refresh_wordbook_after_mutation(language)
        except Exception as exc:
            log.warning("wordbook restore after requery failed: %s", exc)

    def _refresh_wordbook_after_mutation(self, language: str) -> None:
        self._wordbook_ctrl.update_saved_words_cache()
        self._wordbook_ctrl.show_inline(language, self._wordbook_sort_option)
        self._remember_last_view_mode(language)

    def _queue_tts_pre_generation(self, entry: VocabularyEntry) -> None:
        if not (
            getattr(self._settings, "tts_enabled", False)
            and getattr(self._settings, "tts_pre_generate_on_save", False)
        ):
            return
        settings_snapshot = Settings(**self._settings.to_dict())
        entry_snapshot = VocabularyEntry.from_dict(entry.to_dict())
        should_start = False
        with self._tts_pregen_lock:
            _append_tts_pre_generation_job(
                self._tts_pregen_queue,
                settings_snapshot,
                entry_snapshot,
            )
            if not self._tts_pregen_active:
                self._tts_pregen_active = True
                should_start = True
        if should_start:
            threading.Thread(
                target=self._run_tts_pre_generation_loop,
                name="jelly-dict-tts-pregen",
                daemon=True,
            ).start()

    def _run_tts_pre_generation_loop(self) -> None:
        from app.anki.tts.pipeline import TTSPipeline
        from app.services.tts_audio_service import pre_generate_entry_audio_with_pipeline

        pipelines: dict[tuple[object, ...], TTSPipeline] = {}

        while True:
            with self._tts_pregen_lock:
                if not self._tts_pregen_queue:
                    self._tts_pregen_active = False
                    return
                settings, entry = self._tts_pregen_queue.pop(0)
            try:
                key = _tts_pre_generation_pipeline_key(settings)
                pipeline = pipelines.get(key)
                if pipeline is None:
                    pipeline = TTSPipeline(settings)
                    pipelines[key] = pipeline
                generated = pre_generate_entry_audio_with_pipeline(
                    entry, settings, pipeline,
                )
                if generated:
                    log.info("TTS pre-generated %s file(s) for %s", generated, entry.word)
            except Exception as exc:
                log.warning("TTS pre-generation failed for %s: %s", entry.word, exc)

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
        self._refresh_recent_if_visible()

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
        self._start_saved_words_cache_load()
        self._refresh_recent_if_visible()
        self.status.showMessage(f"{language} {count}개 삭제됨 (Excel)")

    def _confirm_suggestion(
        self, typed: str, suggestion: str, detected_language: str
    ) -> bool:
        """Ask the user whether the dictionary's headword matches
        their intent. Returns True if they accept (continue saving),
        False to abort and let them re-enter."""
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setWindowTitle("혹시 이걸 찾으셨나요?")
        msg.setText(
            f"입력하신 <b>{typed}</b> 와 사전이 반환한 표제어가 다릅니다.\n"
            f"혹시 <b>{suggestion}</b> 을 찾으신 건가요?"
        )
        accept = msg.addButton("네, 그걸로 저장", QtWidgets.QMessageBox.AcceptRole)
        reject = msg.addButton("아니요, 다시 입력", QtWidgets.QMessageBox.RejectRole)
        msg.exec()
        return msg.clickedButton() is accept

    @QtCore.Slot()
    def _clear_recent(self) -> None:
        removed = self.input_view.recent_count()
        try:
            snapshot = self._cache.snapshot_recent_lookups()
            self._cache.clear_recent()
        except Exception as exc:
            log.warning("clear recent failed: %s", exc)
            self.status.showMessage("최근 단어 목록 지우기 실패")
            return
        self._refresh_recent(remember=True)
        if removed <= 0:
            self.status.showMessage("최근 단어 목록을 지웠습니다")
            return
        self.status.showMessage(f"최근 단어 {removed}개 삭제됨")
        self.show_undo_toast(
            f"{removed}개를 삭제했습니다.",
            lambda: self._restore_recent(snapshot, removed),
        )

    def _restore_recent(
        self,
        snapshot: list[tuple[str, str, str | None, str]],
        removed: int,
    ) -> None:
        try:
            self._cache.restore_recent_lookups(snapshot)
        except Exception as exc:
            log.warning("restore recent failed: %s", exc)
            self.status.showMessage(f"최근 단어 되돌리기 실패: {exc}")
            return
        self._refresh_recent(remember=True)
        self.status.showMessage(f"{removed}개 삭제를 되돌렸습니다.")

    def _open_developer_tools(self) -> None:
        dlg = DeveloperToolsDialog(self)
        dlg.exec()

    # ---------- OCR input helper -----------------------------------

    def _open_image_for_ocr(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "사진 선택",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.heic)",
        )
        if path:
            self._start_ocr_for_path(path)

    @QtCore.Slot(str)
    def _start_ocr_for_path(self, path_text: str, temp_path: Path | None = None) -> None:
        if self._is_ocr_running():
            self.status.showMessage("이미 사진 텍스트 인식 중입니다.")
            if temp_path is not None:
                ocr_temp_files.remove_temp_file(temp_path)
            return

        image_path = Path(path_text).expanduser()
        self._cleanup_current_ocr_temp()
        self._ocr_temp_path = temp_path
        self.input_view.show_ocr_image(str(image_path))
        self.status.showMessage("사진 텍스트 인식 중...")

        thread = QtCore.QThread(self)
        worker = OcrWorker(self._ocr_provider, image_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ocr_finished)
        worker.failed.connect(self._on_ocr_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_ocr_worker_refs)
        thread.finished.connect(thread.deleteLater)
        self._ocr_thread = thread
        self._ocr_worker = worker
        thread.start()

    @QtCore.Slot(object)
    def _start_ocr_for_clipboard_image(self, image_obj: object) -> None:
        if self._is_ocr_running():
            self.status.showMessage("이미 사진 텍스트 인식 중입니다.")
            return
        if not isinstance(image_obj, QtGui.QImage) or image_obj.isNull():
            self.status.showMessage("붙여넣은 이미지가 비어 있습니다.")
            return
        image_dir = ocr_temp_files.temp_dir()
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"paste-{uuid4().hex}.png"
        if not image_obj.save(str(image_path), "PNG"):
            log.warning("clipboard image save failed: %s", image_path)
            self.status.showMessage("붙여넣은 이미지 저장 실패")
            return
        self._start_ocr_for_path(str(image_path), temp_path=image_path)

    def _is_ocr_running(self) -> bool:
        if self._ocr_thread is None:
            return False
        try:
            return self._ocr_thread.isRunning()
        except RuntimeError:
            self._clear_ocr_worker_refs()
            return False

    def _clear_ocr_worker_refs(self) -> None:
        self._ocr_thread = None
        self._ocr_worker = None

    @QtCore.Slot()
    def _cleanup_current_ocr_temp(self) -> None:
        ocr_temp_files.remove_temp_file(self._ocr_temp_path)
        self._ocr_temp_path = None

    @QtCore.Slot(object)
    def _on_ocr_finished(self, result) -> None:
        tokens = [token.text for token in getattr(result, "tokens", [])]
        self.input_view.set_ocr_tokens(tokens)
        self.status.showMessage(f"OCR 후보 {len(tokens)}개")

    @QtCore.Slot(str)
    def _on_ocr_failed(self, message: str) -> None:
        log.warning("ocr failed: %s", message)
        self.input_view.set_ocr_error("인식 실패")
        self.status.showMessage("사진 텍스트 인식 실패")

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
        if self._is_lookup_running() or self._is_ocr_running():
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
            if self._worker_thread is not None and self._worker_thread.isRunning():
                self._worker_thread.quit()
                self._worker_thread.wait(2000)
        except Exception as exc:
            log.warning("worker thread cleanup failed: %s", exc)
        try:
            if self._ocr_thread is not None and self._ocr_thread.isRunning():
                self._ocr_thread.quit()
                self._ocr_thread.wait(2000)
        except Exception as exc:
            log.warning("ocr thread cleanup failed: %s", exc)
        try:
            if not self._stop_saved_words_cache_load():
                QtWidgets.QMessageBox.information(
                    self,
                    "단어장 확인 중",
                    "저장된 단어 상태 확인이 끝난 뒤 종료해주세요.",
                )
                event.ignore()
                return
        except Exception as exc:
            log.warning("saved words cache cleanup failed: %s", exc)
        self._cleanup_current_ocr_temp()
        ocr_temp_files.cleanup_temp_dir()
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
