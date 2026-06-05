from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.widgets.wordbook_items import WordbookDisplayItem, WordbookItem
from app.ui.word_input_builder import build_word_input_ui
from app.ui.word_input_components import (
    BULK_INPUT_SPLIT_RE,
    HERO_TO_WORDBOOK_SPACING,
    NORMAL_LIST_HEIGHT,
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    ROOT_LAYOUT_SPACING,
    ROOT_MARGIN_EXPANDED,
    ROOT_MARGIN_NORMAL,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
    ElideLabel,
    FlowLayout,
    LoadingSpinner,
    MenuTextButton,
    OcrCandidateChip,
    QueueJobChip,
    RightClickFilter,
    WordbookListWidget,
    _compact_detection_status,
    _elide,
    _repolish,
    _resource_icon,
    split_bulk_input,
)
from app.ui.word_input_events import WordInputEventsMixin
from app.ui.word_input_lists import WordInputListMixin
from app.ui.word_input_menus import WordInputMenuMixin
from app.ui.word_input_ocr import WordInputOcrMixin
from app.ui.word_input_queue import WordInputQueueMixin


class WordInputView(
    WordInputEventsMixin,
    WordInputListMixin,
    WordInputQueueMixin,
    WordInputOcrMixin,
    WordInputMenuMixin,
    QtWidgets.QWidget,
):
    """Command-center style word input with a compact recent list."""

    submitted = QtCore.Signal(str, str)  # word, forced_language ("" = auto)
    bulkSubmitted = QtCore.Signal(object, str)  # list[str], forced_language
    jobCancelRequested = QtCore.Signal(str)  # job_id
    jobRetryRequested = QtCore.Signal(str)  # job_id
    bulkRetryFailedRequested = QtCore.Signal()
    bulkClearFailedRequested = QtCore.Signal()
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
        self._build_ui()

    def _build_ui(self) -> None:
        build_word_input_ui(self)

    def _submit(self) -> None:
        word = self.input.text().strip()
        if not word:
            return
        bulk_words = split_bulk_input(word)
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
        self.lookup_btn.setText(
            "일괄 조회" if len(split_bulk_input(text)) > 1 else "조회"
        )
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

    def set_lookup_busy(self, busy: bool) -> None:
        if self._lookup_busy == busy:
            return
        self._lookup_busy = busy
        self._update_lookup_visibility(self.input.text())
