from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.widgets.anki_export_button import AnkiExportButton
from app.ui.widgets.language_menu_item import LanguageMenuItem
from app.ui.widgets.pill_scrollbar import PillScrollBar
from app.ui.widgets.wordbook_items import (
    WordbookDisplayItem,
    WordbookItem,
    coerce_wordbook_item,
    filter_wordbook_items,
)
from app.ui.widgets.wordbook_row import WordbookRow

NORMAL_LIST_HEIGHT = 348
ROOT_MARGIN_NORMAL = (64, 8, 64, 16)
ROOT_MARGIN_EXPANDED = (36, 14, 36, 16)
HERO_TO_WORDBOOK_SPACING = 4
ROOT_LAYOUT_SPACING = 6
RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources"
RECENT_EMPTY_TEXT = "최근 기록 없음"
RECENT_FILTER_EMPTY_TEXT = "검색 결과 없음"
WORDBOOK_EMPTY_TEXT = "저장된 단어 없음"
WORDBOOK_FILTER_EMPTY_TEXT = "검색 결과 없음"
BULK_INPUT_SPLIT_RE = re.compile(r"[\r\n,;，、]+")


def _resource_icon(name: str) -> QtGui.QIcon:
    return QtGui.QIcon(str(RESOURCE_DIR / "icons" / name))


def _repolish(widget: QtWidgets.QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class ElideLabel(QtWidgets.QLabel):
    def __init__(
        self,
        text: str = "",
        *,
        mode: QtCore.Qt.TextElideMode = QtCore.Qt.ElideMiddle,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self._mode = mode
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        super().setText(self._elided())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        super().setText(self._elided())

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API
        hint = super().sizeHint()
        if self._full_text:
            hint.setWidth(self.fontMetrics().horizontalAdvance(self._full_text) + 4)
        return hint

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def _elided(self) -> str:
        return self.fontMetrics().elidedText(
            self._full_text,
            self._mode,
            max(80, self.width()),
        )


class MenuTextButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._chevron_size = 8
        self._chevron_gap = 6
        self.setFixedHeight(34)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.icon = QtGui.QIcon()
        button_feature = getattr(QtWidgets.QStyleOptionButton, "ButtonFeature", None)
        has_menu = (
            getattr(button_feature, "HasMenu", None)
            if button_feature is not None
            else getattr(QtWidgets.QStyleOptionButton, "HasMenu", None)
        )
        if has_menu is not None:
            option.features &= ~has_menu
        self.style().drawControl(QtWidgets.QStyle.CE_PushButton, option, painter, self)

        font = QtGui.QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QtGui.QFont.Weight.Bold)
        font_metrics = QtGui.QFontMetricsF(font)
        text = self.text()
        text_width = math.ceil(font_metrics.horizontalAdvance(text))
        total_width = text_width + self._chevron_gap + self._chevron_size
        left = round((self.width() - total_width) / 2)
        center_y = self.height() / 2
        text_bounds = font_metrics.tightBoundingRect(text)
        baseline = center_y - (text_bounds.top() + text_bounds.bottom()) / 2

        color = QtGui.QColor("#d4cec4")
        if not self.isEnabled():
            color = QtGui.QColor("#6f6b64")
        elif self.underMouse():
            color = QtGui.QColor("#e7e1d6")

        painter.setPen(color)
        painter.setFont(font)
        painter.drawText(QtCore.QPointF(left, baseline), text)

        chevron_left = left + text_width + self._chevron_gap
        chevron_center_y = round(center_y + 0.5)
        pen = QtGui.QPen(color, 2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(
            chevron_left + 1,
            chevron_center_y - 2,
            chevron_left + self._chevron_size // 2,
            chevron_center_y + 2,
        )
        painter.drawLine(
            chevron_left + self._chevron_size - 1,
            chevron_center_y - 2,
            chevron_left + self._chevron_size // 2,
            chevron_center_y + 2,
        )
        painter.end()



class RightClickFilter(QtCore.QObject):
    rightClicked = QtCore.Signal()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.RightButton:
                self.rightClicked.emit()
                return True
        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            if event.button() == QtCore.Qt.LeftButton:
                self.rightClicked.emit()
                return True
        return super().eventFilter(obj, event)


class OcrCandidateChip(QtWidgets.QPushButton):
    doubleClicked = QtCore.Signal()
    rightClicked = QtCore.Signal()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.RightButton:
            self.rightClicked.emit()
        super().mousePressEvent(event)


class QueueJobChip(QtWidgets.QPushButton):
    rightClicked = QtCore.Signal()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.RightButton:
            self.rightClicked.emit()
            return
        super().mousePressEvent(event)


class WordbookListWidget(QtWidgets.QListWidget):
    """Trackpad-friendly scrolling for the wordbook list."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_remainder = 0.0
        self._pending_deselect_item: QtWidgets.QListWidgetItem | None = None
        self._deselect_timer = QtCore.QTimer(self)
        self._deselect_timer.setSingleShot(True)
        self._deselect_timer.timeout.connect(self._apply_pending_deselect)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBar(PillScrollBar(QtCore.Qt.Vertical, self))
        self.verticalScrollBar().setSingleStep(16)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._cancel_pending_deselect()
        if (
            event.button() == QtCore.Qt.LeftButton
            and self.selectionMode() == QtWidgets.QAbstractItemView.ExtendedSelection
            and self._is_plain_click(event)
        ):
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.isSelected():
                self._pending_deselect_item = item
                interval = QtWidgets.QApplication.doubleClickInterval() + 40
                self._deselect_timer.start(interval)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        self._cancel_pending_deselect()
        if (
            event.button() == QtCore.Qt.LeftButton
            and self.selectionMode() == QtWidgets.QAbstractItemView.ExtendedSelection
            and self._is_plain_click(event)
        ):
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentItem(item)
                item.setSelected(True)
                self.itemDoubleClicked.emit(item)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        bar = self.verticalScrollBar()
        pixel_y = event.pixelDelta().y()
        if pixel_y:
            self._scroll_by(pixel_y * 0.62)
            event.accept()
            return

        angle_y = event.angleDelta().y()
        if angle_y:
            self._scroll_by((angle_y / 120.0) * bar.singleStep() * 2.2)
            event.accept()
            return

        super().wheelEvent(event)

    def _scroll_by(self, delta: float) -> None:
        bar = self.verticalScrollBar()
        self._wheel_remainder += delta
        whole_delta = int(self._wheel_remainder)
        if whole_delta == 0:
            return
        self._wheel_remainder -= whole_delta
        bar.setValue(bar.value() - whole_delta)

    def _is_plain_click(self, event: QtGui.QMouseEvent) -> bool:
        modifiers = event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier
        return modifiers == QtCore.Qt.KeyboardModifier.NoModifier

    def _cancel_pending_deselect(self) -> None:
        self._deselect_timer.stop()
        self._pending_deselect_item = None

    def _apply_pending_deselect(self) -> None:
        item = self._pending_deselect_item
        self._pending_deselect_item = None
        if item is None or self.row(item) < 0 or not item.isSelected():
            return
        item.setSelected(False)


class WordInputView(QtWidgets.QWidget):
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
        # Debounce timer for the wordbook search field — avoids re-rendering
        # the list on every keystroke when the user types fast.
        self._search_debounce = QtCore.QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(120)
        self._search_debounce.timeout.connect(self._render_current_list)
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*ROOT_MARGIN_NORMAL)
        layout.setSpacing(ROOT_LAYOUT_SPACING)
        self._root_layout = layout

        self.top_area = QtWidgets.QFrame()
        self.top_area.setObjectName("topArea")
        top_layout = QtWidgets.QVBoxLayout(self.top_area)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)
        layout.addWidget(self.top_area)

        self.title = QtWidgets.QLabel("jelly dict")
        self.title.setObjectName("heroTitle")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        top_layout.addWidget(self.title)

        top_layout.addSpacing(6)

        self.command_panel = QtWidgets.QFrame()
        self.command_panel.setObjectName("commandPanel")
        panel_layout = QtWidgets.QVBoxLayout(self.command_panel)
        panel_layout.setContentsMargins(22, 14, 22, 12)
        panel_layout.setSpacing(6)
        top_layout.addWidget(self.command_panel, 0, QtCore.Qt.AlignHCenter)

        self.input = QtWidgets.QLineEdit()
        self.input.setObjectName("heroInput")
        self.input.setPlaceholderText("단어를 입력하세요")
        font = self.input.font()
        font.setFamily("Apple SD Gothic Neo")
        font.setPointSize(15)
        self.input.setFont(font)
        self.input.setMinimumHeight(38)
        self.input.installEventFilter(self)
        panel_layout.addWidget(self.input)

        self.ocr_area = QtWidgets.QFrame()
        self.ocr_area.setObjectName("ocrArea")
        self.ocr_area.setVisible(False)
        self.ocr_area.setMaximumHeight(0)
        ocr_layout = QtWidgets.QVBoxLayout(self.ocr_area)
        ocr_layout.setContentsMargins(0, 2, 0, 4)
        ocr_layout.setSpacing(6)

        preview_row = QtWidgets.QHBoxLayout()
        preview_row.setContentsMargins(0, 0, 0, 0)
        preview_row.setSpacing(8)
        ocr_layout.addLayout(preview_row)

        self.ocr_thumbnail = QtWidgets.QLabel()
        self.ocr_thumbnail.setObjectName("ocrThumbnail")
        self.ocr_thumbnail.setFixedSize(74, 52)
        self.ocr_thumbnail.setScaledContents(False)
        preview_row.addWidget(self.ocr_thumbnail)

        self.ocr_status = QtWidgets.QLabel("")
        self.ocr_status.setObjectName("ocrMutedLabel")
        preview_row.addWidget(self.ocr_status, 1)

        self.ocr_clear_btn = QtWidgets.QPushButton("×")
        self.ocr_clear_btn.setObjectName("ocrCloseButton")
        preview_row.addWidget(self.ocr_clear_btn)

        candidates_header = QtWidgets.QHBoxLayout()
        self.ocr_candidates_label = QtWidgets.QLabel("OCR 후보 (더블클릭: 편집, 우클릭: 삭제)")
        candidates_header.addWidget(self.ocr_candidates_label)
        candidates_header.addStretch(1)

        self.ocr_bulk_lookup_btn = QtWidgets.QPushButton("선택/전체 후보 조회")
        self.ocr_bulk_lookup_btn.setObjectName("ocrBulkLookupButton")
        self.ocr_bulk_lookup_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.ocr_bulk_lookup_btn.setEnabled(False)
        self.ocr_bulk_lookup_btn.clicked.connect(self._on_ocr_bulk_lookup_clicked)
        candidates_header.addWidget(self.ocr_bulk_lookup_btn)
        ocr_layout.addLayout(candidates_header)

        self.ocr_candidates = QtWidgets.QFrame()
        self.ocr_candidates.setObjectName("ocrChipPanel")
        self.ocr_candidates_layout = FlowLayout(self.ocr_candidates, spacing=6)
        self.ocr_candidates_layout.setContentsMargins(0, 0, 0, 0)
        ocr_layout.addWidget(self.ocr_candidates)

        panel_layout.addWidget(self.ocr_area)

        self.queue_panel = QtWidgets.QFrame()
        self.queue_panel.setObjectName("queuePanel")
        self.queue_panel.setVisible(False)
        queue_layout = QtWidgets.QVBoxLayout(self.queue_panel)
        queue_layout.setContentsMargins(4, 4, 4, 4)
        queue_layout.setSpacing(4)

        queue_header = QtWidgets.QHBoxLayout()
        queue_title = QtWidgets.QLabel("조회 대기열")
        queue_title.setObjectName("queueTitle")
        self.queue_count_label = QtWidgets.QLabel("0개 대기 중")
        self.queue_count_label.setObjectName("queueCount")
        queue_header.addWidget(queue_title)
        queue_header.addWidget(self.queue_count_label)
        queue_header.addStretch(1)

        self.queue_retry_failed_btn = QtWidgets.QPushButton("실패 재시도")
        self.queue_retry_failed_btn.setObjectName("queueHeaderLink")
        self.queue_retry_failed_btn.setVisible(False)
        self.queue_retry_failed_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.queue_retry_failed_btn.clicked.connect(self.bulkRetryFailedRequested.emit)
        queue_header.addWidget(self.queue_retry_failed_btn)

        self.queue_clear_failed_btn = QtWidgets.QPushButton("실패 지우기")
        self.queue_clear_failed_btn.setObjectName("queueHeaderLinkDanger")
        self.queue_clear_failed_btn.setVisible(False)
        self.queue_clear_failed_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.queue_clear_failed_btn.clicked.connect(self.bulkClearFailedRequested.emit)
        queue_header.addWidget(self.queue_clear_failed_btn)

        queue_layout.addLayout(queue_header)

        self.queue_chips_frame = QtWidgets.QFrame()
        self.queue_chips_layout = FlowLayout(self.queue_chips_frame, spacing=6)
        self.queue_chips_layout.setContentsMargins(0, 2, 0, 2)
        queue_layout.addWidget(self.queue_chips_frame)

        panel_layout.addWidget(self.queue_panel)

        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        panel_layout.addLayout(controls)
        controls.addStretch(1)

        self.lang_button = MenuTextButton("자동 감지")
        self.lang_button.setObjectName("languageSelector")
        self.lang_button.setMenu(self._build_language_menu())
        controls.addWidget(self.lang_button)

        self.ocr_model_btn = MenuTextButton("Apple Vision")
        self.ocr_model_btn.setObjectName("ocrModelSelector")
        self._ocr_menu = QtWidgets.QMenu(self)
        self._ocr_menu.setObjectName("languageMenu")
        self._ocr_menu.aboutToShow.connect(self._rebuild_ocr_model_menu)
        self.ocr_model_btn.setMenu(self._ocr_menu)
        controls.addWidget(self.ocr_model_btn)

        self.image_btn = QtWidgets.QPushButton("")
        self.image_btn.setObjectName("ocrImageButton")
        self.image_btn.setIcon(_resource_icon("photo_mark.svg"))
        self.image_btn.setIconSize(QtCore.QSize(30, 30))
        self.image_btn.setToolTip("사진에서 단어 후보 추출")
        self._hover_icons[self.image_btn] = (
            _resource_icon("photo_mark.svg"),
            _resource_icon("photo_mark_active.svg"),
        )
        self.image_btn.installEventFilter(self)
        controls.addWidget(self.image_btn)

        self.lookup_btn = QtWidgets.QPushButton("조회")
        self.lookup_btn.setObjectName("primaryButton")
        self.lookup_btn.setDefault(True)
        self.lookup_btn.setEnabled(False)
        self.lookup_slot = QtWidgets.QFrame()
        self.lookup_slot.setObjectName("lookupSlot")
        self.lookup_slot.setMaximumWidth(0)
        self.lookup_slot.setMinimumWidth(0)
        lookup_slot_layout = QtWidgets.QHBoxLayout(self.lookup_slot)
        lookup_slot_layout.setContentsMargins(0, 0, 0, 0)
        lookup_slot_layout.setSpacing(0)
        lookup_slot_layout.addWidget(self.lookup_btn)

        self.lookup_busy = QtWidgets.QFrame()
        self.lookup_busy.setObjectName("lookupBusy")
        lookup_busy_layout = QtWidgets.QHBoxLayout(self.lookup_busy)
        lookup_busy_layout.setContentsMargins(0, 0, 0, 0)
        lookup_busy_layout.setSpacing(6)
        self.lookup_spinner = LoadingSpinner()
        self.lookup_spinner.setObjectName("lookupSpinner")
        lookup_busy_layout.addWidget(self.lookup_spinner)
        self.lookup_busy_label = QtWidgets.QLabel("조회 중")
        self.lookup_busy_label.setObjectName("lookupBusyLabel")
        lookup_busy_layout.addWidget(self.lookup_busy_label)
        self.lookup_busy.setVisible(False)
        lookup_slot_layout.addWidget(self.lookup_busy)
        controls.addWidget(self.lookup_slot)

        self.lookup_width_animation = QtCore.QPropertyAnimation(
            self.lookup_slot, b"maximumWidth", self
        )
        self.lookup_width_animation.setDuration(160)
        self.lookup_width_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        layout.addSpacing(HERO_TO_WORDBOOK_SPACING)

        self.recent_panel = QtWidgets.QFrame()
        self.recent_panel.setObjectName("recentPanel")
        self.recent_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding
        )
        recent_layout = QtWidgets.QVBoxLayout(self.recent_panel)
        recent_layout.setContentsMargins(20, 14, 20, 14)
        recent_layout.setSpacing(10)
        layout.addWidget(self.recent_panel, 1, QtCore.Qt.AlignHCenter)

        recent_header = QtWidgets.QHBoxLayout()
        recent_header.setContentsMargins(2, 0, 2, 0)
        recent_header.setSpacing(10)
        recent_layout.addLayout(recent_header)

        self.wordbook_expand_btn = QtWidgets.QPushButton("확대")
        self.wordbook_expand_btn.setObjectName("wordbookExpandButton")
        self.wordbook_expand_btn.setToolTip("단어장 크게 보기")
        self.wordbook_expand_btn.setVisible(False)
        recent_header.addWidget(self.wordbook_expand_btn)

        self.recent_title_btn = MenuTextButton("최근 단어")
        self.recent_title_btn.setObjectName("recentTitleButton")
        self.recent_title_btn.setMenu(self._build_word_list_menu())
        recent_header.addWidget(self.recent_title_btn)

        self.wordbook_sort_btn = MenuTextButton("최신순")
        self.wordbook_sort_btn.setObjectName("wordbookSortButton")
        self.wordbook_sort_btn.setVisible(False)
        self.wordbook_sort_btn.setMenu(self._build_wordbook_sort_menu())
        recent_header.addWidget(self.wordbook_sort_btn)

        self.wordbook_stats = QtWidgets.QLabel("")
        self.wordbook_stats.setObjectName("wordbookStats")
        self.wordbook_stats.setVisible(False)
        recent_header.addWidget(self.wordbook_stats)

        recent_header.addStretch(1)
        self.clear_recent_btn = QtWidgets.QPushButton("목록 지우기")
        self.clear_recent_btn.setObjectName("ghostButton")
        self.clear_recent_btn.setToolTip("Excel/캐시는 유지, 표시만 지움")
        recent_header.addWidget(self.clear_recent_btn)
        self.wordbook_export_btn = AnkiExportButton()
        self.wordbook_export_btn.setVisible(False)
        recent_header.addWidget(self.wordbook_export_btn)
        self.wordbook_delete_btn = QtWidgets.QPushButton("선택 삭제", self.recent_panel)
        self.wordbook_delete_btn.setObjectName("wordbookDeleteButton")
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)

        self.wordbook_search = QtWidgets.QLineEdit()
        self.wordbook_search.setObjectName("wordbookSearch")
        self.wordbook_search.setPlaceholderText("단어 / 뜻 검색...")
        self.wordbook_search.installEventFilter(self)
        self.wordbook_search.setVisible(False)
        recent_layout.addWidget(self.wordbook_search)

        self.recent_list = WordbookListWidget()
        self.recent_list.setObjectName("recentList")
        self.recent_list.setFlow(QtWidgets.QListView.TopToBottom)
        self.recent_list.setWrapping(False)
        self.recent_list.setResizeMode(QtWidgets.QListView.Adjust)
        self.recent_list.setMovement(QtWidgets.QListView.Static)
        self.recent_list.setSpacing(7)
        self.recent_list.setUniformItemSizes(True)
        self.recent_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.recent_list.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.recent_list.installEventFilter(self)
        recent_layout.addWidget(self.recent_list, 1)

        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(14)
        footer.setContentsMargins(0, 10, 0, 0)
        layout.addLayout(footer)
        footer.addStretch(1)

        self.status_summary = ElideLabel("")
        self.status_summary.setObjectName("statusSummary")
        self.status_summary.setAlignment(QtCore.Qt.AlignCenter)
        self.status_summary.setWordWrap(False)
        self.status_summary.setMinimumWidth(0)
        self.status_summary.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
        )
        self.status_summary.setMaximumWidth(780)
        footer.addWidget(self.status_summary)

        self.settings_btn = QtWidgets.QPushButton("설정")
        self.settings_btn.setObjectName("footerSettingsButton")
        footer.addWidget(self.settings_btn)
        footer.addStretch(1)

        self.input.returnPressed.connect(self._submit)
        self.input.textChanged.connect(self._update_lookup_visibility)
        self.lookup_btn.clicked.connect(self._submit)
        self.image_btn.clicked.connect(self.imageOpenRequested.emit)
        self.ocr_clear_btn.clicked.connect(self.clear_ocr_image)
        self.recent_list.itemDoubleClicked.connect(self._open_recent_entry)
        self.recent_list.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.recent_list.currentItemChanged.connect(
            lambda _current, _previous: self._on_list_selection_changed()
        )
        self.clear_recent_btn.clicked.connect(self.clearRecentRequested.emit)
        self.wordbook_export_btn.exportRequested.connect(self.wordbookExportRequested.emit)
        self.wordbook_export_btn.settingsRequested.connect(self.openSettingsRequested.emit)
        self.input.textEdited.connect(lambda _text: self.prewarmRequested.emit())
        self.wordbook_delete_btn.clicked.connect(self._request_wordbook_delete)
        self.wordbook_expand_btn.clicked.connect(self._toggle_wordbook_expanded)
        # Restart the debounce timer on every keystroke; final render
        # happens once the user pauses typing.
        self.wordbook_search.textChanged.connect(
            lambda _text: self._search_debounce.start()
        )
        self.settings_btn.clicked.connect(self.openSettingsRequested.emit)
        self._update_lookup_visibility(self.input.text())

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

    def _build_language_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("languageMenu")
        for label, subtitle, value in [
            ("자동 감지", "입력 문자로 영어/일본어를 판단", ""),
            ("English", "네이버 영어사전으로 조회", "en"),
            ("日本語", "네이버 일본어사전으로 조회", "ja"),
        ]:
            action = QtWidgets.QWidgetAction(menu)
            item = LanguageMenuItem(label, subtitle)
            item.clicked.connect(lambda _=False, v=value: self._set_language(v))
            action.setDefaultWidget(item)
            menu.addAction(action)
            self._language_actions[value] = action
        menu.aboutToShow.connect(self._sync_language_menu)
        return menu

    def _build_word_list_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("languageMenu")
        for label, subtitle, value in [
            ("최근 단어", "최근 조회한 단어 보기", "recent"),
            ("영어 단어장", "저장된 영어 단어 관리", "en"),
            ("일본어 단어장", "저장된 일본어 단어 관리", "ja"),
        ]:
            action = QtWidgets.QWidgetAction(menu)
            item = LanguageMenuItem(label, subtitle)
            item.clicked.connect(lambda _=False, v=value, m=menu: self._open_word_list(v, m))
            action.setDefaultWidget(item)
            menu.addAction(action)
            self._word_list_actions[value] = action
        menu.aboutToShow.connect(self._sync_word_list_menu)
        return menu

    def _build_wordbook_sort_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("languageMenu")
        for opt, subtitle in [
            ("최신순", "새로 저장한 단어 먼저"),
            ("오래된순", "처음 저장한 단어 먼저"),
            ("가나다순", "단어 이름 기준 정렬"),
        ]:
            action = QtWidgets.QWidgetAction(menu)
            item = LanguageMenuItem(opt, subtitle)
            item.clicked.connect(lambda _=False, o=opt, m=menu: self._select_sort(o, m))
            action.setDefaultWidget(item)
            menu.addAction(action)
            self._sort_actions[opt] = action
        menu.aboutToShow.connect(self._sync_sort_menu)
        return menu

    def _select_sort(self, option: str, menu: QtWidgets.QMenu) -> None:
        menu.close()
        self._on_sort_changed(option)

    def _on_sort_changed(self, option: str) -> None:
        self.wordbook_sort_btn.setText(option)
        self.wordbookSortChanged.emit(option)

    def _rebuild_ocr_model_menu(self) -> None:
        """Rebuild on every open so Google Vision availability tracks the
        live API-key state (set/cleared in the settings dialog)."""
        from app.storage import secret_store

        self._ocr_menu.clear()
        self._ocr_actions.clear()
        gv_key_set = secret_store.is_set("google_vision_api_key")
        items = [
            ("apple_vision", "Apple Vision", "macOS 로컬 OCR", True),
            (
                "google_vision",
                "Google Vision",
                "사용자 API 키" if gv_key_set else "API 키 입력 후 사용 가능",
                gv_key_set,
            ),
        ]
        for name, label, subtitle, enabled in items:
            action = QtWidgets.QWidgetAction(self._ocr_menu)
            item = LanguageMenuItem(label, subtitle)
            item.setEnabled(enabled)
            if enabled:
                item.clicked.connect(
                    lambda _=False, n=name, lbl=label: self._select_ocr_provider(n, lbl)
                )
            action.setDefaultWidget(item)
            self._ocr_menu.addAction(action)
            self._ocr_actions[name] = action
        self._sync_ocr_menu()

    def _select_ocr_provider(self, name: str, label: str) -> None:
        self._ocr_provider = name
        self.ocr_model_btn.setText(label)
        self._ocr_menu.close()
        self.ocrProviderChanged.emit(name)

    def set_ocr_provider_label(self, name: str) -> None:
        """Sync the button label with externally-loaded settings."""
        self._ocr_provider = name if name in ("apple_vision", "google_vision") else "apple_vision"
        self.ocr_model_btn.setText(
            "Google Vision" if name == "google_vision" else "Apple Vision"
        )

    def _open_word_list(self, language: str, menu: QtWidgets.QMenu) -> None:
        menu.close()
        self.openWordListRequested.emit(language)

    def _set_language(self, value: str) -> None:
        self._forced_language = value
        labels = {"": "자동 감지", "en": "English", "ja": "日本語"}
        self.lang_button.setText(labels.get(value, "자동 감지"))
        menu = self.lang_button.menu()
        if menu is not None:
            menu.close()

    def _sync_language_menu(self) -> None:
        for value, action in self._language_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._forced_language)

    def _sync_word_list_menu(self) -> None:
        for value, action in self._word_list_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._list_mode)

    def _sync_sort_menu(self) -> None:
        for value, action in self._sort_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self.wordbook_sort_btn.text())

    def _sync_ocr_menu(self) -> None:
        for value, action in self._ocr_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._ocr_provider)

    def _open_recent_entry(self, item: QtWidgets.QListWidgetItem) -> None:
        payload = item.data(QtCore.Qt.UserRole)
        if isinstance(payload, tuple) and len(payload) == 2:
            word, language = payload
            self.recentEntryRequested.emit(str(word), str(language))



    def reset_input(self) -> None:
        self.input.clear()
        self.input.setFocus()

    def set_detection_label(self, text: str) -> None:
        self._detection_status = _compact_detection_status(text)
        self._render_footer_status_summary()

    def show_ocr_image(self, image_path: str) -> None:
        pixmap = QtGui.QPixmap(image_path)
        if not pixmap.isNull():
            self.ocr_thumbnail.setPixmap(
                pixmap.scaled(
                    self.ocr_thumbnail.size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            )
        else:
            self.ocr_thumbnail.clear()
        self._ocr_tokens = []
        self._ocr_selected_tokens = []
        self._ocr_chip_buttons = {}
        self._set_ocr_status("사진 텍스트 인식 중...")
        self._render_ocr_chips()
        self._set_ocr_area_visible(True)

    def set_ocr_tokens(self, tokens: list[str]) -> None:
        self._ocr_tokens = list(tokens)
        if tokens:
            self._set_ocr_status(f"후보 {len(tokens)}개")
            self._render_ocr_chips()
        else:
            self._set_ocr_status("인식된 단어 후보 없음")
            self._render_ocr_chips()
        self._set_ocr_area_visible(True)

    def set_ocr_error(self, message: str) -> None:
        self._ocr_tokens = []
        self._set_ocr_status(message)
        self._render_ocr_chips()
        self._set_ocr_area_visible(True)

    def clear_ocr_image(self) -> None:
        self.ocr_thumbnail.clear()
        self._ocr_tokens = []
        self._ocr_selected_tokens = []
        self._ocr_chip_buttons = {}
        self._set_ocr_status("")
        self._render_ocr_chips()
        self._set_ocr_area_visible(False)
        self.ocrCleared.emit()

    def _set_ocr_area_visible(self, visible: bool) -> None:
        if self._ocr_height_animation is not None:
            self._ocr_height_animation.stop()

        if visible:
            self.ocr_area.setVisible(True)
            self.ocr_area.adjustSize()
        target_height = self.ocr_area.sizeHint().height() if visible else 0
        start_height = self.ocr_area.height() if self.ocr_area.isVisible() else 0

        self._ocr_height_animation = QtCore.QVariantAnimation(self)
        self._ocr_height_animation.setStartValue(start_height)
        self._ocr_height_animation.setEndValue(target_height)
        self._ocr_height_animation.setDuration(180)
        self._ocr_height_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._ocr_height_animation.valueChanged.connect(
            lambda value: self.ocr_area.setMaximumHeight(int(value))
        )
        self._ocr_height_animation.finished.connect(
            lambda: self._finish_ocr_area_animation(visible)
        )
        self._ocr_height_animation.start()

    def _finish_ocr_area_animation(self, visible: bool) -> None:
        if visible:
            self.ocr_area.setMaximumHeight(16777215)
            return
        self.ocr_area.setVisible(False)
        self.ocr_area.setMaximumHeight(0)

    def _set_ocr_status(self, text: str) -> None:
        self.ocr_status.setText(text)

    def _render_ocr_chips(self, selectable: bool = True) -> None:
        layout = self.ocr_candidates_layout
        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._ocr_chip_buttons = {}
        for token in self._ocr_tokens:
            button = OcrCandidateChip(_elide(token, 28))
            button.setObjectName("ocrChipButton")
            button.setToolTip(f"'{token}' (클릭: 선택, 더블클릭: 편집, 우클릭: 삭제)")
            if selectable:
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, t=token: self._choose_ocr_token(t, checked)
                )
                button.setChecked(token in self._ocr_selected_tokens)
            else:
                button.clicked.connect(lambda _=False, t=token: self._fill_from_ocr_token(t))

            button.doubleClicked.connect(lambda t=token: self._edit_ocr_token(t))
            button.rightClicked.connect(lambda t=token: self._delete_ocr_token(t))

            self._ocr_chip_buttons[token] = button
            layout.addWidget(button)

        if hasattr(self, "ocr_bulk_lookup_btn"):
            self.ocr_bulk_lookup_btn.setEnabled(bool(self._ocr_tokens))

        self.ocr_candidates.updateGeometry()
        self.ocr_area.updateGeometry()

    def _edit_ocr_token(self, token: str) -> None:
        new_text, ok = QtWidgets.QInputDialog.getText(
            self, "후보 수정", "후보 단어 수정:", text=token
        )
        if not ok:
            return
        new_text = new_text.strip()
        if not new_text or new_text == token:
            return

        if token in self._ocr_tokens:
            idx = self._ocr_tokens.index(token)
            self._ocr_tokens[idx] = new_text

        if token in self._ocr_selected_tokens:
            s_idx = self._ocr_selected_tokens.index(token)
            self._ocr_selected_tokens[s_idx] = new_text

        self._render_ocr_chips()

    def _delete_ocr_token(self, token: str) -> None:
        self._ocr_tokens = [t for t in self._ocr_tokens if t != token]
        self._ocr_selected_tokens = [t for t in self._ocr_selected_tokens if t != token]
        self._set_ocr_status(f"후보 {len(self._ocr_tokens)}개")
        self._render_ocr_chips()

    def _on_ocr_bulk_lookup_clicked(self) -> None:
        targets = self._ocr_selected_tokens if self._ocr_selected_tokens else self._ocr_tokens
        if targets:
            self.ocrBulkLookupRequested.emit(targets, self._forced_language)

    def _choose_ocr_token(self, token: str, selected: bool) -> None:
        if selected:
            if token not in self._ocr_selected_tokens:
                self._ocr_selected_tokens.append(token)
            self._fill_from_ocr_token(token)
            self.ocrTokenSelected.emit(token)
            return
        self._ocr_selected_tokens = [
            selected_token
            for selected_token in self._ocr_selected_tokens
            if selected_token != token
        ]
        if self._ocr_selected_tokens:
            self._fill_from_ocr_token(self._ocr_selected_tokens[-1])
        else:
            self.input.clear()
            self.input.setFocus()

    def _fill_from_ocr_token(self, token: str) -> None:
        self.input.setText(token)
        self.input.setFocus()
        self.input.selectAll()

    def selected_ocr_tokens(self) -> list[str]:
        return list(self._ocr_selected_tokens)

    def set_recent(self, items: list[tuple[str, str, str, str]]) -> None:
        """Each item is (word, language, hint, status). Hint is the first Korean
        meaning shown after an em-dash so the user can verify saves at a
        glance."""
        previous_mode = self._list_mode
        display_items = items[:20]
        self._list_mode = "recent"
        self._recent_items = list(display_items)
        self._wordbook_items = []
        self.top_area.setVisible(not self._wordbook_expanded)
        self.top_area.setMaximumHeight(0 if self._wordbook_expanded else 16777215)
        self._apply_wordbook_chrome_state()
        self.recent_title_btn.setText("최근 단어")
        self.wordbook_expand_btn.setVisible(True)
        self.wordbook_sort_btn.setVisible(False)
        self.wordbook_stats.setVisible(False)
        self.clear_recent_btn.setVisible(True)
        self.clear_recent_btn.setEnabled(bool(display_items))
        self.wordbook_export_btn.setVisible(False)
        self.wordbook_export_btn.setEnabled(True)
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)
        self._search_debounce.stop()
        if previous_mode != "recent":
            self.wordbook_search.clear()
        self.wordbook_search.setPlaceholderText("최근 단어 검색...")
        self.wordbook_search.setVisible(bool(display_items))
        self.wordbook_search.setMaximumHeight(16777215)
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.recent_list.setMaximumHeight(16777215)
        if not display_items:
            self.recent_list.clear()
            self._add_empty_list_item(RECENT_EMPTY_TEXT, NORMAL_LIST_HEIGHT)
            return
        self._render_recent()

    def recent_count(self) -> int:
        return len(self._recent_items)

    def _render_current_list(self) -> None:
        if self._list_mode == "recent":
            self._render_recent()
            return
        self._render_wordbook()

    def _render_recent(self) -> None:
        if self._list_mode != "recent":
            return
        needle = self.wordbook_search.text().strip().lower()
        if needle:
            display_items = [
                item
                for item in self._recent_items
                if needle in item[0].lower()
                or needle in item[1].lower()
                or needle in item[2].lower()
            ]
        else:
            display_items = list(self._recent_items)

        self.recent_list.clear()
        if not display_items:
            self._add_empty_list_item(
                RECENT_FILTER_EMPTY_TEXT if needle else RECENT_EMPTY_TEXT,
                120 if needle else NORMAL_LIST_HEIGHT,
            )
            return
        for word, language, hint, status in display_items:
            prefix = "✓ " if status == "saved" else ""
            label = f"{prefix}[{language}] {word}"
            if hint:
                label += f"  —  {hint}"
            display_label = _elide(label, 58)
            qt_item = QtWidgets.QListWidgetItem(label)
            qt_item.setFlags(QtCore.Qt.ItemIsEnabled)
            qt_item.setText(display_label)
            qt_item.setData(QtCore.Qt.UserRole, (word, language))
            qt_item.setToolTip("")
            qt_item.setSizeHint(QtCore.QSize(620, 36))
            self.recent_list.addItem(qt_item)

    def set_lookup_queue(self, jobs: list[tuple[str, str, str]]) -> None:
        # Clear existing chips
        while self.queue_chips_layout.count() > 0:
            item = self.queue_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not jobs:
            self.queue_panel.setVisible(False)
            return

        self.queue_panel.setVisible(True)
        running_count = sum(1 for _, status, _ in jobs if status == "running")
        pending_count = sum(1 for _, status, _ in jobs if status == "pending")
        failed_count = sum(1 for _, status, _ in jobs if status == "failed")

        status_text = ""
        if running_count > 0:
            status_text += f"조회 중 {running_count}개"
        if pending_count > 0:
            if status_text:
                status_text += ", "
            status_text += f"대기 {pending_count}개"
        if failed_count > 0:
            if status_text:
                status_text += ", "
            status_text += f"실패 {failed_count}개"
        self.queue_count_label.setText(status_text)

        self.queue_retry_failed_btn.setVisible(failed_count > 0)
        self.queue_clear_failed_btn.setVisible(failed_count > 0)

        MAX_VISIBLE_CHIPS = 10
        has_more = len(jobs) > MAX_VISIBLE_CHIPS
        display_jobs = jobs[:MAX_VISIBLE_CHIPS - 1] if has_more else jobs

        for word, status, job_id in display_jobs:
            if status == "running":
                chip = QtWidgets.QPushButton()
                chip.setObjectName("queueChipRunning")
                chip.setText(f"진행 · {_elide(word, 22)}")
                chip.setCursor(QtCore.Qt.ArrowCursor)
                chip.setToolTip(f"'{word}' (조회 중...)")
            elif status == "failed":
                chip = QueueJobChip()
                chip.setObjectName("queueChipFailed")
                chip.setText(f"실패 · {_elide(word, 22)}")
                chip.setCursor(QtCore.Qt.PointingHandCursor)
                chip.setToolTip(f"'{word}' (조회 실패. 클릭: 재시도, 우클릭: 삭제)")
                chip.clicked.connect(lambda checked=False, jid=job_id: self.jobRetryRequested.emit(jid))
                chip.rightClicked.connect(lambda jid=job_id: self.jobCancelRequested.emit(jid))
            else:
                chip = QtWidgets.QPushButton()
                chip.setObjectName("queueChipPending")
                chip.setText(_elide(word, 24))
                chip.setCursor(QtCore.Qt.PointingHandCursor)
                chip.setToolTip(f"'{word}' (대기열에서 취소하려면 클릭)")
                chip.clicked.connect(lambda checked=False, jid=job_id: self.jobCancelRequested.emit(jid))

            self.queue_chips_layout.addWidget(chip)

        if has_more:
            more_count = len(jobs) - len(display_jobs)
            more_chip = QtWidgets.QPushButton()
            more_chip.setObjectName("queueChipMore")
            more_chip.setText(f"+ 외 {more_count}개")
            more_chip.setCursor(QtCore.Qt.PointingHandCursor)

            hidden_jobs = jobs[len(display_jobs):]
            remaining_words = [w for w, _, _ in hidden_jobs]
            if len(remaining_words) > 30:
                tooltip_text = "대기 단어 (클릭하면 상세 조작 가능):\n" + ", ".join(remaining_words[:30]) + f"\n... 외 {len(remaining_words) - 30}개"
            else:
                tooltip_text = "대기 단어 (클릭하면 상세 조작 가능):\n" + ", ".join(remaining_words)
            more_chip.setToolTip(tooltip_text)

            def show_more_menu() -> None:
                menu = QtWidgets.QMenu(more_chip)
                menu.setObjectName("languageMenu")
                for word, status, job_id in hidden_jobs:
                    if status == "failed":
                        retry_act = menu.addAction(f"실패 · {word} (조회 재시도)")
                        retry_act.triggered.connect(lambda checked=False, jid=job_id: self.jobRetryRequested.emit(jid))
                        delete_act = menu.addAction(f"{word} (대기 삭제)")
                        delete_act.triggered.connect(lambda checked=False, jid=job_id: self.jobCancelRequested.emit(jid))
                    else:
                        cancel_act = menu.addAction(f"{word} (대기 취소)")
                        cancel_act.triggered.connect(lambda checked=False, jid=job_id: self.jobCancelRequested.emit(jid))

                pos = more_chip.mapToGlobal(QtCore.QPoint(0, more_chip.height()))
                menu.exec(pos)

            more_chip.clicked.connect(show_more_menu)
            self.queue_chips_layout.addWidget(more_chip)

    def set_wordbook(self, language: str, items: list[WordbookItem]) -> None:
        previous_mode = self._list_mode
        self._list_mode = language
        self._wordbook_items = [coerce_wordbook_item(item) for item in items]
        title = "일본어 단어장" if language == "ja" else "영어 단어장"
        self.recent_title_btn.setText(title)
        self.top_area.setVisible(not self._wordbook_expanded)
        self.top_area.setMaximumHeight(0 if self._wordbook_expanded else 16777215)
        self._apply_wordbook_chrome_state()
        self.wordbook_expand_btn.setVisible(True)
        self.wordbook_sort_btn.setVisible(True)
        self.wordbook_stats.setVisible(True)
        self.clear_recent_btn.setVisible(False)
        self.wordbook_export_btn.setVisible(True)
        self.wordbook_export_btn.setEnabled(bool(self._wordbook_items))
        self.wordbook_export_btn.set_language(language)
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)
        self._search_debounce.stop()
        self.wordbook_search.setPlaceholderText("단어 / 뜻 / 태그 / 메모 검색...")
        if previous_mode != language:
            self.wordbook_search.clear()
        self.wordbook_search.setVisible(True)
        self.wordbook_search.setMaximumHeight(16777215)
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.recent_list.setMaximumHeight(16777215)
        # Mode transition: drop any items from the previous (recent) mode
        # so leftover text labels don't bleed through under the wordbook
        # row widgets we install via setItemWidget.
        self.recent_list.clear()
        self._render_wordbook()

    def _render_wordbook(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        needle = self.wordbook_search.text().strip().lower()
        if needle:
            items = self._filtered_wordbook_items(needle)
        else:
            items = list(self._wordbook_items)

        # Reuse existing items in place when the count matches: avoids
        # tearing down + rebuilding QWidget instances on every render
        # (matters when filtering a large wordbook). Visual output is
        # identical to the previous "clear + addItem in a loop" path.
        self.recent_list.setUpdatesEnabled(False)
        try:
            self.recent_list.clearSelection()
            current = self.recent_list.count()
            target = len(items)
            if target == 0:
                self.recent_list.clear()
                self._add_empty_list_item(
                    WORDBOOK_FILTER_EMPTY_TEXT if needle else WORDBOOK_EMPTY_TEXT,
                    120 if needle else NORMAL_LIST_HEIGHT,
                )
                self._on_list_selection_changed()
                return
            for i in range(min(current, target)):
                item = items[i]
                qt_item = self.recent_list.item(i)
                qt_item.setText("")
                qt_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                qt_item.setData(QtCore.Qt.UserRole, (item.word, item.language))
                qt_item.setToolTip("")
                qt_item.setSizeHint(QtCore.QSize(620, 62))
                self._set_wordbook_row_widget(qt_item, item)
            # Append any extra rows.
            for i in range(current, target):
                item = items[i]
                qt_item = QtWidgets.QListWidgetItem()
                qt_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                qt_item.setData(QtCore.Qt.UserRole, (item.word, item.language))
                qt_item.setToolTip("")
                qt_item.setSizeHint(QtCore.QSize(620, 62))
                self.recent_list.addItem(qt_item)
                self._set_wordbook_row_widget(qt_item, item)
            # Drop trailing rows from the previous render.
            while self.recent_list.count() > target:
                trailing_item = self.recent_list.item(self.recent_list.count() - 1)
                self._remove_wordbook_row_widget(trailing_item)
                self.recent_list.takeItem(self.recent_list.count() - 1)
        finally:
            self.recent_list.setUpdatesEnabled(True)
        self._on_list_selection_changed()

    def _build_wordbook_row(
        self,
        item: WordbookDisplayItem,
    ) -> WordbookRow:
        row = WordbookRow(item.language, item.word, item.reading, item.hint)
        row.editRequested.connect(self._edit_wordbook_from_row)
        row.deleteRequested.connect(self._delete_wordbook_from_row)
        return row

    def _set_wordbook_row_widget(
        self,
        qt_item: QtWidgets.QListWidgetItem,
        item: WordbookDisplayItem,
    ) -> None:
        self._remove_wordbook_row_widget(qt_item)
        self.recent_list.setItemWidget(qt_item, self._build_wordbook_row(item))

    def _remove_wordbook_row_widget(self, qt_item: QtWidgets.QListWidgetItem) -> None:
        old_widget = self.recent_list.itemWidget(qt_item)
        if old_widget is not None:
            self.recent_list.removeItemWidget(qt_item)
            old_widget.hide()
            old_widget.setParent(None)
            old_widget.deleteLater()

    def _filtered_wordbook_items(self, needle: str) -> list[WordbookDisplayItem]:
        return filter_wordbook_items(self._wordbook_items, needle)

    def _add_empty_list_item(self, text: str, height: int) -> None:
        item = QtWidgets.QListWidgetItem(text)
        item.setFlags(QtCore.Qt.NoItemFlags)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setSizeHint(QtCore.QSize(620, height))
        self.recent_list.addItem(item)

    def _toggle_wordbook_expanded(self) -> None:
        if self._list_mode not in ("recent", "en", "ja"):
            return
        self._wordbook_expanded = not self._wordbook_expanded
        self._apply_wordbook_chrome_state()
        self._animate_wordbook_layout()

    def _apply_wordbook_chrome_state(self) -> None:
        expanded = self._wordbook_expanded and self._list_mode in ("recent", "en", "ja")
        self.wordbook_expand_btn.setText("축소" if expanded else "확대")
        self.wordbook_expand_btn.setToolTip(
            "입력 영역 보이기" if expanded else "목록 크게 보기"
        )
        self.recent_panel.setProperty("expanded", expanded)
        self.recent_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding if expanded else QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Expanding,
        )
        self.recent_panel.setMinimumWidth(720 if expanded else 860)
        self.recent_panel.setMaximumWidth(10000 if expanded else 980)
        self._root_layout.setAlignment(
            self.recent_panel,
            QtCore.Qt.Alignment() if expanded else QtCore.Qt.AlignHCenter,
        )
        self._root_layout.setContentsMargins(
            *(ROOT_MARGIN_EXPANDED if expanded else ROOT_MARGIN_NORMAL)
        )
        _repolish(self.recent_panel)

    def _animate_wordbook_layout(self) -> None:
        if self._list_mode not in ("recent", "en", "ja"):
            return
        if self._top_height_animation is not None:
            self._top_height_animation.stop()

        duration = 240
        if not self._wordbook_expanded:
            self.top_area.setVisible(True)
            if self.top_area.maximumHeight() == 0:
                self.top_area.setMaximumHeight(0)

        full_top_height = self.top_area.sizeHint().height()
        top_start = self.top_area.height() if self.top_area.isVisible() else 0
        top_end = 0 if self._wordbook_expanded else full_top_height
        self._top_height_animation = QtCore.QVariantAnimation(self)
        self._top_height_animation.setStartValue(top_start)
        self._top_height_animation.setEndValue(top_end)
        self._top_height_animation.setDuration(duration)
        self._top_height_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._top_height_animation.valueChanged.connect(
            lambda value: self.top_area.setMaximumHeight(int(value))
        )
        self._top_height_animation.finished.connect(self._finish_top_animation)
        self._top_height_animation.start()

        self.wordbook_search.setVisible(
            self._list_mode in ("en", "ja") or bool(self._recent_items)
        )
        self.wordbook_search.setMaximumHeight(16777215)

    def _finish_top_animation(self) -> None:
        if self._wordbook_expanded:
            self.top_area.setVisible(False)
            self.top_area.setMaximumHeight(0)
            return
        self.top_area.setVisible(True)
        self.top_area.setMaximumHeight(16777215)

    def _finish_search_animation(self) -> None:
        self.wordbook_search.setVisible(self._list_mode in ("en", "ja"))
        self.wordbook_search.setMaximumHeight(16777215)

    def _on_list_selection_changed(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        self._update_wordbook_toolbar_state()

    def _update_wordbook_toolbar_state(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        selected = self._selected_wordbook_words()
        visible_count = self._visible_wordbook_count()
        selected_count = len(selected)
        stats = f"{visible_count}개"
        if selected_count:
            stats += f" · 선택 {selected_count}개"
        self.wordbook_stats.setText(stats)
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)
        self.wordbook_delete_btn.setText("선택 삭제")
        self._sync_wordbook_row_actions(selected_count)

    def _sync_wordbook_row_actions(self, selected_count: int) -> None:
        current_item = self.recent_list.currentItem()
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            row = self.recent_list.itemWidget(item)
            if isinstance(row, WordbookRow):
                row.set_actions_visible(
                    item is current_item and item.isSelected(),
                    max(1, selected_count),
                )

    def _visible_wordbook_count(self) -> int:
        count = 0
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                count += 1
        return count

    def _selected_wordbook_words(self) -> list[str]:
        words: list[str] = []
        for item in self.recent_list.selectedItems():
            payload = item.data(QtCore.Qt.UserRole)
            if not (isinstance(payload, tuple) and len(payload) == 2):
                continue
            word, language = payload
            if language == self._list_mode and isinstance(word, str) and word.strip():
                words.append(word.strip())
        return words

    def _select_visible_wordbook_items(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        self.recent_list.clearSelection()
        first_selectable: QtWidgets.QListWidgetItem | None = None
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                if first_selectable is None:
                    first_selectable = item
        if first_selectable is not None:
            self.recent_list.setCurrentItem(first_selectable)
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                item.setSelected(True)
        self._update_wordbook_toolbar_state()

    def _wordbook_words_for_row_action(self, word: str) -> list[str]:
        if self._list_mode not in ("en", "ja"):
            return []
        selected = self._selected_wordbook_words()
        if word in selected:
            return selected
        return [word] if word.strip() else []

    def _edit_wordbook_from_row(self, word: str) -> None:
        if self._list_mode in ("en", "ja") and word.strip():
            self.wordbookEditRequested.emit(self._list_mode, word.strip())

    def _delete_wordbook_from_row(self, word: str) -> None:
        words = self._wordbook_words_for_row_action(word)
        if words:
            self.wordbookDeleteRequested.emit(self._list_mode, words)

    def _copy_selected_wordbook_items(self) -> None:
        words = self._selected_wordbook_words()
        if not words:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(words))
        self.status_summary.setText(f"선택한 단어 {len(words)}개 복사됨")

    def _request_wordbook_delete(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        words = self._selected_wordbook_words()
        if words:
            self.wordbookDeleteRequested.emit(self._list_mode, words)

    def _request_wordbook_export(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        self.wordbookExportRequested.emit(self._list_mode, "settings", False)

    def set_status_summary(self, text: str) -> None:
        self._base_status_summary = text
        self._render_footer_status_summary()

    def _render_footer_status_summary(self) -> None:
        parts = [part for part in (self._base_status_summary, self._detection_status) if part]
        self.status_summary.setText(" · ".join(parts))

    def set_anki_export_status(self, text: str) -> None:
        self.wordbook_export_btn.set_status_text(text)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if self._first_image_path(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        path = self._first_image_path(event.mimeData())
        if path is not None:
            self.imageDropped.emit(str(path))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if isinstance(watched, QtWidgets.QPushButton) and watched in self._hover_icons:
            normal_icon, active_icon = self._hover_icons[watched]
            if event.type() == QtCore.QEvent.Enter:
                watched.setIcon(active_icon)
            elif event.type() == QtCore.QEvent.Leave:
                watched.setIcon(normal_icon)
        if watched is self.input and event.type() in (
            QtCore.QEvent.FocusIn,
            QtCore.QEvent.KeyPress,
        ):
            self.prewarmRequested.emit()
        if watched is self.input and event.type() == QtCore.QEvent.KeyPress:
            key_event = event
            if isinstance(key_event, QtGui.QKeyEvent) and key_event.matches(
                QtGui.QKeySequence.Paste
            ):
                return self._paste_clipboard_image_if_available()
        if event.type() == QtCore.QEvent.KeyPress and isinstance(event, QtGui.QKeyEvent):
            if watched is getattr(self, "wordbook_search", None):
                return self._handle_list_search_key_press(event)
            if watched is getattr(self, "recent_list", None):
                return self._handle_list_key_press(event)
        return super().eventFilter(watched, event)

    def _handle_list_search_key_press(self, event: QtGui.QKeyEvent) -> bool:
        if self.wordbook_search.isHidden():
            return False
        if event.key() == QtCore.Qt.Key_Escape and self.wordbook_search.text():
            self.wordbook_search.clear()
            self._search_debounce.stop()
            self._render_current_list()
            return True
        if not self._is_plain_key_press(event):
            return False
        if event.key() == QtCore.Qt.Key_Down:
            self._flush_pending_search_render()
            return self._focus_list_item(self._first_selectable_list_item())
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._flush_pending_search_render()
            return self._open_list_item(self._first_selectable_list_item())
        return False

    def _handle_list_key_press(self, event: QtGui.QKeyEvent) -> bool:
        if (
            event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
            and self._is_plain_key_press(event)
        ):
            return self._open_current_or_first_list_item()
        if self._list_mode not in ("en", "ja"):
            return False
        if event.matches(QtGui.QKeySequence.Copy):
            if self._selected_wordbook_words():
                self._copy_selected_wordbook_items()
                return True
            return False
        if event.matches(QtGui.QKeySequence.SelectAll):
            self._select_visible_wordbook_items()
            return True
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            if self._selected_wordbook_words():
                self._request_wordbook_delete()
                return True
            return False
        return False

    def _is_plain_key_press(self, event: QtGui.QKeyEvent) -> bool:
        modifiers = event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier
        return modifiers == QtCore.Qt.KeyboardModifier.NoModifier

    def _flush_pending_search_render(self) -> None:
        if self._search_debounce.isActive():
            self._search_debounce.stop()
            self._render_current_list()

    def _first_selectable_list_item(self) -> QtWidgets.QListWidgetItem | None:
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if self._is_openable_list_item(item):
                return item
        return None

    def _current_or_first_selectable_list_item(self) -> QtWidgets.QListWidgetItem | None:
        current = self.recent_list.currentItem()
        if current is not None and self._is_openable_list_item(current):
            return current
        return self._first_selectable_list_item()

    def _focus_list_item(self, item: QtWidgets.QListWidgetItem | None) -> bool:
        if item is None:
            return False
        self.recent_list.setFocus(QtCore.Qt.OtherFocusReason)
        self.recent_list.setCurrentItem(item)
        if self._list_mode != "recent" and not item.isSelected():
            item.setSelected(True)
        self._on_list_selection_changed()
        return True

    def _is_openable_list_item(self, item: QtWidgets.QListWidgetItem) -> bool:
        if self._list_mode == "recent":
            return bool(item.flags() & QtCore.Qt.ItemIsEnabled)
        return bool(item.flags() & QtCore.Qt.ItemIsSelectable)

    def _open_current_or_first_list_item(self) -> bool:
        return self._open_list_item(self._current_or_first_selectable_list_item())

    def _open_list_item(self, item: QtWidgets.QListWidgetItem | None) -> bool:
        if item is None:
            return False
        self.recent_list.setCurrentItem(item)
        self._open_recent_entry(item)
        return True

    def _paste_clipboard_image_if_available(self) -> bool:
        clipboard = QtGui.QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        path = self._first_image_path(mime_data)
        if path is not None:
            self.imageDropped.emit(str(path))
            return True
        if mime_data.hasImage():
            image_data = mime_data.imageData()
            if isinstance(image_data, QtGui.QImage) and not image_data.isNull():
                self.clipboardImagePasted.emit(image_data)
                return True
            if isinstance(image_data, QtGui.QPixmap) and not image_data.isNull():
                self.clipboardImagePasted.emit(image_data.toImage())
                return True
        return False

    def _first_image_path(self, mime_data: QtCore.QMimeData) -> Path | None:
        if not mime_data.hasUrls():
            return None
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in allowed:
                return path
        return None


def _elide(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _compact_detection_status(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text.replace("감지된 언어:", "감지:")
    return " ".join(text.split())


def split_bulk_input(text: str) -> list[str]:
    """Split explicit separators while preserving phrases with spaces."""
    pieces = [piece.strip() for piece in BULK_INPUT_SPLIT_RE.split(text or "")]
    out: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if not piece:
            continue
        key = piece.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(piece)
    return out


class LoadingSpinner(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(15, 15)

    def set_running(self, running: bool) -> None:
        if running and not self._timer.isActive():
            self._timer.start()
        elif not running and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        base_pen = QtGui.QPen(QtGui.QColor(231, 225, 214, 62), 2)
        base_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(base_pen)
        painter.drawEllipse(rect)

        active_pen = QtGui.QPen(QtGui.QColor("#e8744f"), 2)
        active_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(active_pen)
        painter.drawArc(rect, (90 - self._angle) * 16, -110 * 16)
        painter.end()


class FlowLayout(QtWidgets.QLayout):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        margin: int = 0,
        spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QtWidgets.QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QtWidgets.QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QtWidgets.QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> QtCore.Qt.Orientations:
        return QtCore.Qt.Orientations(QtCore.Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QtCore.QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QtCore.QSize:
        return self.minimumSize()

    def minimumSize(self) -> QtCore.QSize:
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QtCore.QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _do_layout(self, rect: QtCore.QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()
