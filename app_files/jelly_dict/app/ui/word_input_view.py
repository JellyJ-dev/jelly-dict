from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.widgets.wordbook_items import WordbookDisplayItem, WordbookItem
from app.ui.word_input_builder import build_word_input_ui
from app.ui.word_input_events import InputPresenter
from app.ui.word_input_lists import WordbookPresenter
from app.ui.word_input_menus import MenuPresenter
from app.ui.word_input_ocr import OcrPresenter
from app.ui.word_input_parts.chips import OcrCandidateChip, QueueJobChip
from app.ui.word_input_parts.flow_layout import FlowLayout
from app.ui.word_input_parts.labels_buttons import (
    ElideLabel,
    MenuTextButton,
    RightClickFilter,
    _repolish,
    _resource_icon,
)
from app.ui.word_input_parts.layout_constants import (
    HERO_TO_WORDBOOK_SPACING,
    NORMAL_LIST_HEIGHT,
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    ROOT_LAYOUT_SPACING,
    ROOT_MARGIN_EXPANDED,
    ROOT_MARGIN_NORMAL,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
)
from app.ui.word_input_parts.spinner import LoadingSpinner
from app.ui.word_input_parts.text_parsing import (
    BULK_INPUT_SPLIT_RE,
    _compact_detection_status,
    _elide,
    split_bulk_input,
)
from app.ui.word_input_parts.wordbook_list import WordbookListWidget
from app.ui.word_input_queue import QueuePresenter
from app.ui.word_input_ui_refs import WordInputUiRefs


class WordInputView(QtWidgets.QWidget):
    """Command-center style word input with a compact recent list."""

    submitted = QtCore.Signal(str, str)  # word, forced_language ("" = auto)
    bulkSubmitted = QtCore.Signal(object, str)  # list[str], forced_language
    jobCancelRequested = QtCore.Signal(str)  # job_id
    jobRetryRequested = QtCore.Signal(str)  # job_id
    bulkRetryFailedRequested = QtCore.Signal()
    bulkClearFailedRequested = QtCore.Signal()
    lookupStopRequested = QtCore.Signal()
    wordbookSortChanged = QtCore.Signal(str)
    wordbookEditRequested = QtCore.Signal(str, str)  # language, word
    ocrBatchSubmitted = QtCore.Signal(object, str)  # list[str], forced_language
    ocrBulkLookupRequested = QtCore.Signal(list, str)  # list[str], forced_language
    clearRecentRequested = QtCore.Signal()
    openWordListRequested = QtCore.Signal(str)
    openSettingsRequested = QtCore.Signal()
    recentEntryRequested = QtCore.Signal(str, str)
    wordbookDeleteRequested = QtCore.Signal(str, object)
    wordbookExportRequested = QtCore.Signal(str, str, bool)
    imageOpenRequested = QtCore.Signal()
    imageDropped = QtCore.Signal(str)
    clipboardImagePasted = QtCore.Signal(object)
    ocrTokenSelected = QtCore.Signal(str)
    ocrProviderChanged = QtCore.Signal(str)  # "apple_vision" | "google_vision"
    ocrCleared = QtCore.Signal()
    prewarmRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._forced_language = ""
        self._list_mode = "recent"
        self._recent_items: list[tuple[str, str, str, str]] = []
        self._wordbook_items: list[WordbookDisplayItem] = []
        self._wordbook_item_keys: dict[int, object] = {}
        self._wordbook_row_pool: dict[object, tuple[QtWidgets.QListWidgetItem, object]] = {}
        self._wordbook_display_by_key: dict[object, WordbookDisplayItem] = {}
        self._wordbook_dirty_keys: set[object] = set()
        self._wordbook_visible_keys: set[object] = set()
        self._wordbook_empty_item: QtWidgets.QListWidgetItem | None = None
        self._wordbook_expanded = False
        self._lookup_busy = False
        self._ocr_tokens: list[str] = []
        self._ocr_selected_tokens: list[str] = []
        self._ocr_chip_buttons: dict[str, QtWidgets.QPushButton] = {}
        self._ocr_provider = "apple_vision"
        self._clear_search_after_expand = False
        self._pressed_selected_wordbook_item: QtWidgets.QListWidgetItem | None = None
        self._base_status_summary = ""
        self._detection_status = ""
        self._list_height_animation: QtCore.QVariantAnimation | None = None
        self._search_height_animation: QtCore.QVariantAnimation | None = None
        self._top_height_animation: QtCore.QVariantAnimation | None = None
        self._ocr_height_animation: QtCore.QVariantAnimation | None = None
        self._hover_icons: dict[QtWidgets.QPushButton, tuple[QtGui.QIcon, QtGui.QIcon]] = {}
        self._language_actions: dict[str, QtWidgets.QWidgetAction | QtCore.QObject] = {}
        self._word_list_actions: dict[str, QtWidgets.QWidgetAction | QtCore.QObject] = {}
        self._sort_actions: dict[str, QtWidgets.QWidgetAction | QtCore.QObject] = {}
        self._ocr_actions: dict[str, QtWidgets.QWidgetAction | QtCore.QObject] = {}
        self._search_debounce = QtCore.QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(120)
        self._search_debounce.timeout.connect(self._render_current_list)
        self.setAcceptDrops(True)
        self.menu_presenter = MenuPresenter(self)
        self._build_ui()
        self._ui = WordInputUiRefs.capture(self)
        self.menu_presenter.set_ui(self._ui)
        self.input_presenter = InputPresenter(self._ui, self)
        self.queue_presenter = QueuePresenter(self._ui, self)
        self.ocr_presenter = OcrPresenter(self._ui, self)
        self.wordbook_presenter = WordbookPresenter(self._ui, self)

    def _build_ui(self) -> None:
        build_word_input_ui(self)

    def _build_language_menu(self) -> QtWidgets.QMenu:
        return self.menu_presenter._build_language_menu()

    def _build_word_list_menu(self) -> QtWidgets.QMenu:
        return self.menu_presenter._build_word_list_menu()

    def _build_wordbook_sort_menu(self) -> QtWidgets.QMenu:
        return self.menu_presenter._build_wordbook_sort_menu()

    def _rebuild_ocr_model_menu(self) -> None:
        self.menu_presenter._rebuild_ocr_model_menu()

    def _open_recent_entry(self, item: QtWidgets.QListWidgetItem) -> None:
        self.menu_presenter._open_recent_entry(item)

    def set_ocr_provider_label(self, name: str) -> None:
        self.menu_presenter.set_ocr_provider_label(name)

    def _submit(self) -> None:
        word = self.input.text().strip()
        if not word:
            return
        bulk_words = split_bulk_input(word)
        if not bulk_words:
            return
        if len(bulk_words) > 1:
            self.bulkSubmitted.emit(bulk_words, self._forced_language)
            return
        if len(bulk_words) == 1 and BULK_INPUT_SPLIT_RE.search(word):
            word = bulk_words[0]
        if len(self._ocr_selected_tokens) > 1:
            self.ocrBatchSubmitted.emit(list(self._ocr_selected_tokens), self._forced_language)
            return
        self.submitted.emit(word, self._forced_language)

    def _update_lookup_visibility(self, text: str) -> None:
        has_text = bool(text.strip())
        should_show = has_text and not self._lookup_busy
        should_spin = self._lookup_busy
        self.lookup_btn.setText("일괄 조회" if len(split_bulk_input(text)) > 1 else "조회")
        self.lookup_btn.setVisible(should_show)
        self.lookup_busy.setVisible(should_spin)
        self.lookup_spinner.set_running(should_spin)
        target_width = 0
        if should_spin:
            target_width = self.lookup_busy.sizeHint().width()
        elif should_show:
            target_width = self.lookup_btn.sizeHint().width()
        if (
            should_show == self.lookup_btn.isEnabled()
            and self.lookup_slot.maximumWidth() == target_width
        ):
            return
        self.lookup_btn.setEnabled(should_show)
        self.lookup_width_animation.stop()
        self.lookup_width_animation.setStartValue(self.lookup_slot.maximumWidth())
        self.lookup_width_animation.setEndValue(target_width)
        self.lookup_width_animation.start()

    def _set_lookup_busy_impl(self, busy: bool) -> None:
        if self._lookup_busy == busy:
            return
        self._lookup_busy = busy
        self._update_lookup_visibility(self.input.text())

    def set_lookup_busy(self, busy: bool) -> None:
        self.input_presenter.set_lookup_busy(busy)

    def reset_input(self) -> None:
        self.input_presenter.reset_input()

    def set_detection_label(self, text: str) -> None:
        self.input_presenter.set_detection_label(text)

    def set_status_summary(self, text: str) -> None:
        self.input_presenter.set_status_summary(text)

    def set_anki_export_status(self, text: str) -> None:
        self.input_presenter.set_anki_export_status(text)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        self.input_presenter.dragEnterEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        self.input_presenter.dropEvent(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        presenter = getattr(self, "input_presenter", None)
        if presenter is None:
            return QtWidgets.QWidget.eventFilter(self, watched, event)
        return presenter.eventFilter(watched, event)

    def set_lookup_queue(self, jobs: list[tuple[str, str, str]]) -> None:
        self.queue_presenter.set_lookup_queue(jobs)

    def set_ocr_tokens(self, tokens: list[str]) -> None:
        self.ocr_presenter.set_ocr_tokens(tokens)

    def show_ocr_image(self, image_path: str) -> None:
        self.ocr_presenter.show_ocr_image(image_path)

    def set_ocr_error(self, message: str) -> None:
        self.ocr_presenter.set_ocr_error(message)

    def clear_ocr_image(self) -> None:
        self.ocr_presenter.clear_ocr_image()

    def _on_ocr_bulk_lookup_clicked(self) -> None:
        self.ocr_presenter._on_ocr_bulk_lookup_clicked()

    def _choose_ocr_token(self, token: str, selected: bool) -> None:
        self.ocr_presenter._choose_ocr_token(token, selected)

    def selected_ocr_tokens(self) -> list[str]:
        return self.ocr_presenter.selected_ocr_tokens()

    def set_wordbook(self, language: str, items: list[object]) -> None:
        self.wordbook_presenter.set_wordbook(language, items)

    def set_recent(self, items: list[tuple[str, str, str, str]]) -> None:
        self.wordbook_presenter.set_recent(items)

    def recent_count(self) -> int:
        return self.wordbook_presenter.recent_count()

    def selected_wordbook_entry_refs(self) -> list[object]:
        return self.wordbook_presenter.selected_wordbook_entry_refs()

    def _render_current_list(self) -> None:
        self.wordbook_presenter._render_current_list()

    def _render_wordbook(self) -> None:
        self.wordbook_presenter._render_wordbook()

    def _on_list_selection_changed(self) -> None:
        self.wordbook_presenter._on_list_selection_changed()

    def _hydrate_visible_wordbook_rows(self) -> None:
        self.wordbook_presenter._hydrate_visible_wordbook_rows()

    def _request_wordbook_delete(self) -> None:
        self.wordbook_presenter._request_wordbook_delete()

    def _toggle_wordbook_expanded(self) -> None:
        self.wordbook_presenter._toggle_wordbook_expanded()

    def _selected_wordbook_words(self) -> list[str]:
        return self.wordbook_presenter._selected_wordbook_words()

    def _copy_selected_wordbook_items(self) -> None:
        self.wordbook_presenter._copy_selected_wordbook_items()

    def _select_visible_wordbook_items(self) -> None:
        self.wordbook_presenter._select_visible_wordbook_items()
