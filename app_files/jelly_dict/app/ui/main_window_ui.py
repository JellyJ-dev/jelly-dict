from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.storage.settings_store import Settings
from app.ui.preview_editor_view import PreviewEditorView
from app.ui.word_input_view import WordInputView
from app.ui.widgets.pill_scrollbar import install_pill_scrollbars
from app.ui.widgets.transient_status_bar import TransientStatusBar
from app.ui.widgets.undo_toast import UndoToast

log = logging.getLogger(__name__)

_THEME_PATH = Path(__file__).resolve().parent / "resources" / "theme.qss"
_RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources"


def build_main_window_ui(
    window: QtWidgets.QMainWindow,
    *,
    wordbook_sort_option: str,
    settings: Settings,
) -> None:
    central = QtWidgets.QWidget()
    central.setObjectName("appRoot")
    window.setCentralWidget(central)
    root = QtWidgets.QVBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)

    window.input_view = WordInputView()
    window.input_view.wordbook_sort_btn.setText(wordbook_sort_option)
    window.input_view.wordbookSortChanged.connect(window._on_wordbook_sort_changed)
    window.input_view.wordbookEditRequested.connect(window._edit_wordbook_entry)
    window.input_view.clearRecentRequested.connect(lambda: window._recent_ctrl.clear())
    window.input_view.openWordListRequested.connect(window._open_word_list)
    window.input_view.openSettingsRequested.connect(window._open_settings)
    window.input_view.recentEntryRequested.connect(window._open_recent_entry_detail)
    window.input_view.wordbookDeleteRequested.connect(window._delete_wordbook_entries)
    window.input_view.wordbookExportRequested.connect(window._export_apkg)
    window.input_view.ocrProviderChanged.connect(window._on_ocr_provider_changed)
    if hasattr(window.input_view, "prewarmRequested"):
        window.input_view.prewarmRequested.connect(window._browser_prewarm_ctrl.schedule)
    window.input_view.set_ocr_provider_label(settings.ocr_provider)

    input_scroll = QtWidgets.QScrollArea()
    input_scroll.setObjectName("inputScroll")
    input_scroll.setWidgetResizable(True)
    input_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    input_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    input_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    install_pill_scrollbars(input_scroll, horizontal=False)
    input_scroll.setWidget(window.input_view)

    window.preview_view = PreviewEditorView()
    preview_scroll = QtWidgets.QScrollArea()
    preview_scroll.setObjectName("previewScroll")
    preview_scroll.setWidgetResizable(True)
    preview_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    preview_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    preview_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    install_pill_scrollbars(preview_scroll)
    preview_scroll.setWidget(window.preview_view)

    window.stack = QtWidgets.QStackedLayout()
    wrapper = QtWidgets.QWidget()
    wrapper.setLayout(window.stack)
    window.stack.addWidget(input_scroll)
    window.stack.addWidget(preview_scroll)
    root.addWidget(wrapper, 1)
    window._input_page = input_scroll
    window._preview_page = preview_scroll

    apply_theme(window)
    window.status = TransientStatusBar(central)
    window.undo_toast = UndoToast(central)
    window.undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.Undo, window)
    window.undo_shortcut.activated.connect(window.undo_toast.trigger_undo)
    window.close_shortcut = QtGui.QShortcut(
        QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Close),
        window,
    )
    window.close_shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
    window.close_shortcut.activated.connect(window._hide_main_window)


def build_main_window_menu(window: QtWidgets.QMainWindow, settings: Settings) -> None:
    menu = window.menuBar()
    file_menu = menu.addMenu("파일")
    for label, lang in [("영어", "en"), ("일본어", "ja")]:
        action_tsv = QtGui.QAction(f"Anki TSV 내보내기 — {label}...", window)
        action_tsv.triggered.connect(lambda _=False, L=lang: window._export_tsv(L))
        file_menu.addAction(action_tsv)
    file_menu.addSeparator()
    for label, lang in [("영어", "en"), ("일본어", "ja")]:
        action_apkg = QtGui.QAction(f"Anki APKG 내보내기 — {label}...", window)
        action_apkg.triggered.connect(lambda _=False, L=lang: window._export_apkg(L))
        file_menu.addAction(action_apkg)

    tools_menu = menu.addMenu("도구")
    window.preview_toggle_action = QtGui.QAction("저장 전 미리보기", window)
    window.preview_toggle_action.setCheckable(True)
    window.preview_toggle_action.setChecked(settings.show_preview)
    window.preview_toggle_action.toggled.connect(window._on_preview_toggle)
    tools_menu.addAction(window.preview_toggle_action)
    tools_menu.addSeparator()

    prefs = QtGui.QAction("설정...", window)
    prefs.setShortcut("Ctrl+,")
    prefs.triggered.connect(window._open_settings)
    tools_menu.addAction(prefs)

    clear_cache = QtGui.QAction("캐시 비우기", window)
    clear_cache.triggered.connect(window._clear_cache)
    tools_menu.addAction(clear_cache)

    manage_menu = menu.addMenu("관리")
    manage_en = QtGui.QAction("영어 단어장...", window)
    manage_en.setShortcut("Ctrl+L")
    manage_en.triggered.connect(lambda: window._show_wordbook_inline("en"))
    manage_menu.addAction(manage_en)
    manage_ja = QtGui.QAction("일본어 단어장...", window)
    manage_ja.triggered.connect(lambda: window._show_wordbook_inline("ja"))
    manage_menu.addAction(manage_ja)

    view_menu = menu.addMenu("보기")
    developer_tools = QtGui.QAction("개발자 도구", window)
    developer_tools.setShortcut("Ctrl+Shift+I")
    developer_tools.triggered.connect(window._open_developer_tools)
    view_menu.addAction(developer_tools)


def apply_theme(window: QtWidgets.QWidget) -> None:
    try:
        qss = _THEME_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("theme.qss read failed: %s", exc)
        return
    qss = qss.replace(
        "url(resources/",
        f"url({_RESOURCE_ROOT.as_posix()}/",
    )
    window.setStyleSheet(qss)
