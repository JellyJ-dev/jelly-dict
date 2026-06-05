from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.widgets.anki_export_button import AnkiExportButton
from app.ui.word_input_components import (
    HERO_TO_WORDBOOK_SPACING,
    NORMAL_LIST_HEIGHT,
    ROOT_LAYOUT_SPACING,
    ROOT_MARGIN_NORMAL,
    ElideLabel,
    FlowLayout,
    LoadingSpinner,
    MenuTextButton,
    WordbookListWidget,
    _resource_icon,
)

def build_word_input_ui(self) -> None:
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
