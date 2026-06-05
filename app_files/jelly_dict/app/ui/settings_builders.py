from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.dialog_buttons import configure_footer_button
from app.ui.widgets.pill_scrollbar import install_pill_scrollbars
from app.ui.settings_widgets import (
    _PathPicker,
    _muted_label,
    _section_header,
    _settings_combo,
    set_status_state,
)
from app.ui.settings_runtime_mixin import SAMPLE_TEXT_EN, SAMPLE_TEXT_JA


class SettingsBuildMixin:
    # ── layout ─────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.addTab(self._build_general_tab(), "기본")
        self.tabs.addTab(self._build_ocr_tab(), "OCR")
        self.tabs.addTab(self._build_anki_tab(), "Anki")
        root.addWidget(self.tabs, 1)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.setObjectName("settingsButtonBox")
        save_button = button_box.button(QtWidgets.QDialogButtonBox.Save)
        cancel_button = button_box.button(QtWidgets.QDialogButtonBox.Cancel)
        if save_button is not None:
            configure_footer_button(save_button, role="primary", text="저장")
        if cancel_button is not None:
            configure_footer_button(cancel_button, role="secondary", text="취소")
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box, 0, QtCore.Qt.AlignRight)

    def _new_form(self) -> tuple[QtWidgets.QWidget, QtWidgets.QFormLayout]:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("settingsScroll")
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        install_pill_scrollbars(scroll, horizontal=False)
        panel = QtWidgets.QFrame()
        panel.setObjectName("settingsPanel")
        panel.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        scroll.setWidget(panel)
        # Wrap the form in a vertical layout so it sits at the top-left
        # with empty space below, instead of stretching its rows to fill
        # the panel height.
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)
        form_holder = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(form_holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(10)
        layout.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        outer.addWidget(form_holder, 0, QtCore.Qt.AlignTop)
        outer.addStretch(1)
        return scroll, layout

    # ── tab: 기본 ──────────────────────────────────────────────────
    def _build_general_tab(self) -> QtWidgets.QWidget:
        page, layout = self._new_form()

        self.excel_dir = _PathPicker(mode="dir")
        self.excel_en = _PathPicker(mode="file_save", file_filter="Excel (*.xlsx)")
        self.excel_ja = _PathPicker(mode="file_save", file_filter="Excel (*.xlsx)")
        self.anki_dir = _PathPicker(mode="dir")
        self.anki_en = _PathPicker(mode="file_save", file_filter="APKG (*.apkg)")
        self.anki_ja = _PathPicker(mode="file_save", file_filter="APKG (*.apkg)")
        self.deck_name = QtWidgets.QLineEdit()
        self.deck_name.setObjectName("settingsLineEdit")
        self.delay = QtWidgets.QDoubleSpinBox()
        self.delay.setObjectName("settingsSpin")
        self.delay.setRange(0.3, 60.0)
        self.delay.setSingleStep(0.1)
        self.delay.setDecimals(2)
        self.delay.setSuffix(" s")
        self.delay.setToolTip(
            "요청 간격. 너무 짧으면 네이버에서 차단될 수 있습니다 (최소 0.3초)."
        )
        self.cache_check = QtWidgets.QCheckBox("캐시 사용")
        self.preview_check = QtWidgets.QCheckBox("저장 전 미리보기 화면 표시")
        self.dup_combo = _settings_combo()
        for value, label in [
            ("ask", "묻기 (다이얼로그)"),
            ("update_existing", "덮어쓰기"),
            ("merge_examples_and_memo", "병합"),
            ("keep_existing", "기존 유지"),
            ("add_as_new", "새 항목으로 추가"),
        ]:
            self.dup_combo.addItem(label, value)
        self.provider_combo = _settings_combo()
        for value, label in [
            ("naver_crawler", "네이버 사전"),
        ]:
            self.provider_combo.addItem(label, value)

        layout.addRow(_section_header("저장 위치"))
        self._add_form_row(layout, "기본 Excel 폴더", self.excel_dir)
        self._add_form_row(layout, "Excel 파일 (영어)", self.excel_en)
        self._add_form_row(layout, "Excel 파일 (일본어)", self.excel_ja)
        self._add_form_row(layout, "Anki 폴더", self.anki_dir)
        self._add_form_row(layout, "Anki 파일 (영어)", self.anki_en)
        self._add_form_row(layout, "Anki 파일 (일본어)", self.anki_ja)
        self._add_form_row(layout, "Anki 덱 이름", self.deck_name)

        layout.addRow(_section_header("조회 / 저장"))
        self._add_form_row(layout, "요청 간격", self.delay)
        layout.addRow("", self.cache_check)
        layout.addRow("", self.preview_check)
        self._add_form_row(layout, "중복 처리", self.dup_combo)
        self._add_form_row(layout, "사전 소스", self.provider_combo)
        return page

    # ── tab: OCR ───────────────────────────────────────────────────
    def _build_ocr_tab(self) -> QtWidgets.QWidget:
        page, layout = self._new_form()

        self.ocr_combo = _settings_combo()
        self.ocr_combo.addItem("Apple Vision (로컬)", "apple_vision")
        self.ocr_combo.addItem("Google Cloud Vision (사용자 API 키)", "google_vision")

        self.gv_key_edit = QtWidgets.QLineEdit()
        self.gv_key_edit.setObjectName("settingsLineEdit")
        self.gv_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.gv_key_edit.setPlaceholderText("키가 저장되어 있으면 비워두세요")
        self.gv_key_save_btn = QtWidgets.QPushButton("키 저장")
        self.gv_key_save_btn.setObjectName("settingsSecondaryButton")
        self.gv_key_clear_btn = QtWidgets.QPushButton("키 삭제")
        self.gv_key_clear_btn.setObjectName("settingsSecondaryButton")
        self.gv_key_test_btn = QtWidgets.QPushButton("키 테스트")
        self.gv_key_test_btn.setObjectName("settingsSecondaryButton")
        self.gv_key_status = QtWidgets.QLabel("")
        self.gv_key_status.setObjectName("settingsStatus")
        set_status_state(self.gv_key_status, "muted")
        gv_row = QtWidgets.QWidget()
        gv_layout = QtWidgets.QHBoxLayout(gv_row)
        gv_layout.setContentsMargins(0, 0, 0, 0)
        gv_layout.addWidget(self.gv_key_edit, 1)
        gv_layout.addWidget(self.gv_key_save_btn)
        gv_layout.addWidget(self.gv_key_clear_btn)
        gv_layout.addWidget(self.gv_key_test_btn)
        self.gv_key_save_btn.clicked.connect(self._save_gv_key)
        self.gv_key_clear_btn.clicked.connect(self._clear_gv_key)
        self.gv_key_test_btn.clicked.connect(self._test_gv_key)

        self._add_form_row(layout, "OCR 엔진", self.ocr_combo)
        self._add_form_row(layout, "Google Vision 키", gv_row)
        layout.addRow(self.gv_key_status)
        layout.addRow(_muted_label(
            "키는 macOS Keychain에만 저장되며 어떤 파일에도 기록되지 않습니다. "
            "비용은 사용자 본인 GCP 계정 부담."
        ))
        return page

    # ── tab: Anki ──────────────────────────────────────────────────
    def _build_anki_tab(self) -> QtWidgets.QWidget:
        page, layout = self._new_form()

        self.ankiconnect_check = QtWidgets.QCheckBox("AnkiConnect 사용 (실시간 Anki 동기화)")
        self.ankiconnect_check.setToolTip(
            "Anki 데스크톱에 AnkiConnect 애드온이 설치돼 있어야 합니다.\n"
            "활성화 시 단어 삭제가 Anki에도 즉시 반영됩니다."
        )
        self.ankiconnect_url = QtWidgets.QLineEdit()
        self.ankiconnect_url.setObjectName("settingsLineEdit")
        self.ankiconnect_url.setPlaceholderText("http://127.0.0.1:8765")
        self.ankiconnect_test_btn = QtWidgets.QPushButton("연결 테스트")
        self.ankiconnect_test_btn.setObjectName("settingsSecondaryButton")
        self.ankiconnect_status = QtWidgets.QLabel("")
        self.ankiconnect_status.setObjectName("settingsStatus")
        set_status_state(self.ankiconnect_status, "pending")
        url_row = QtWidgets.QWidget()
        url_layout = QtWidgets.QHBoxLayout(url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.addWidget(self.ankiconnect_url, 1)
        url_layout.addWidget(self.ankiconnect_test_btn)
        self.ankiconnect_test_btn.clicked.connect(self._test_ankiconnect)

        layout.addRow(_section_header("AnkiConnect"))
        layout.addRow("", self.ankiconnect_check)
        self._add_form_row(layout, "AnkiConnect URL", url_row)
        layout.addRow("", self.ankiconnect_status)

        # ── TTS ────────────────────────────────────────────────────
        layout.addRow(_section_header("TTS (Anki 카드 음성)"))

        self.tts_install_status = _muted_label("")

        self.tts_install_btn = QtWidgets.QPushButton("Kokoro 설치")
        self.tts_install_btn.setObjectName("settingsSecondaryButton")
        self.tts_install_btn.setToolTip(
            "pip로 Kokoro / soundfile 설치 (Apache-2.0).\n"
            "ffmpeg는 Homebrew가 있으면 함께 자동 설치됩니다."
        )
        self.tts_install_btn.clicked.connect(lambda: self._install_engine("kokoro"))

        self.voicevox_install_btn = QtWidgets.QPushButton("VOICEVOX 설치")
        self.voicevox_install_btn.setObjectName("settingsSecondaryButton")
        self.voicevox_install_btn.setToolTip(
            "Homebrew가 있으면 'brew install --cask voicevox'로 자동 설치, "
            "없으면 다운로드 페이지를 엽니다."
        )
        self.voicevox_install_btn.clicked.connect(self._install_or_open_voicevox)

        self.edge_install_btn = QtWidgets.QPushButton("edge-tts 설치")
        self.edge_install_btn.setObjectName("settingsSecondaryButton")
        self.edge_install_btn.setToolTip(
            "pipx로 별도 venv에 설치 (GPL-3.0 격리). "
            "pipx가 없으면 Homebrew로 pipx부터 설치합니다."
        )
        self.edge_install_btn.clicked.connect(self._install_or_copy_edge)

        # Delete buttons — small trash icon next to each install button.
        # Only enabled when the corresponding engine is detected as
        # installed; otherwise hidden so the row stays clean.
        self.kokoro_uninstall_btn = self._make_uninstall_btn(
            "Kokoro", "Kokoro 패키지 + 모델 캐시(~327MB)를 삭제합니다",
            lambda: self._uninstall_engine("kokoro"),
        )
        self.voicevox_uninstall_btn = self._make_uninstall_btn(
            "VOICEVOX", "Homebrew로 설치한 VOICEVOX를 제거합니다",
            lambda: self._uninstall_engine("voicevox"),
        )
        self.edge_uninstall_btn = self._make_uninstall_btn(
            "edge-tts", "pipx로 설치한 edge-tts를 제거합니다",
            lambda: self._uninstall_engine("edge"),
        )

        install_row = QtWidgets.QWidget()
        install_layout = QtWidgets.QHBoxLayout(install_row)
        install_layout.setContentsMargins(0, 0, 0, 0)
        install_layout.setSpacing(4)
        install_layout.addWidget(self.tts_install_btn)
        install_layout.addWidget(self.kokoro_uninstall_btn)
        install_layout.addSpacing(8)
        install_layout.addWidget(self.voicevox_install_btn)
        install_layout.addWidget(self.voicevox_uninstall_btn)
        install_layout.addSpacing(8)
        install_layout.addWidget(self.edge_install_btn)
        install_layout.addWidget(self.edge_uninstall_btn)
        install_layout.addStretch(1)
        self._add_form_row(layout, "엔진 설치", install_row)
        layout.addRow(self.tts_install_status)

        self.tts_enabled_check = QtWidgets.QCheckBox("TTS 사용 (Anki 카드에 음성 첨부)")
        self.tts_play_front_check = QtWidgets.QCheckBox("앞면 자동 재생")
        self.tts_play_back_check = QtWidgets.QCheckBox("뒷면 자동 재생")
        self.tts_play_examples_check = QtWidgets.QCheckBox("예문 음성도 생성")
        self.tts_pre_generate_check = QtWidgets.QCheckBox("저장 후 TTS 미리 생성")

        self.tts_engine_en_combo = _settings_combo()
        self.tts_voice_en_combo = _settings_combo()
        self.tts_sample_en_btn = QtWidgets.QPushButton("▶")
        self.tts_sample_en_btn.setObjectName("settingsSecondaryButton")
        self.tts_sample_en_btn.setMaximumWidth(40)
        self.tts_sample_en_btn.setToolTip(f"샘플 재생: \"{SAMPLE_TEXT_EN}\"")
        self.tts_engine_en_combo.currentIndexChanged.connect(
            lambda *_: self._refresh_voices("en")
        )
        self.tts_sample_en_btn.clicked.connect(lambda: self._play_sample("en"))

        en_row = QtWidgets.QWidget()
        en_layout = QtWidgets.QHBoxLayout(en_row)
        en_layout.setContentsMargins(0, 0, 0, 0)
        en_layout.addWidget(self.tts_voice_en_combo, 1)
        en_layout.addWidget(self.tts_sample_en_btn)

        self.tts_engine_ja_combo = _settings_combo()
        self.tts_voice_ja_combo = _settings_combo()
        self.tts_voice_add_btn = QtWidgets.QPushButton("+")
        self.tts_voice_add_btn.setObjectName("settingsSecondaryButton")
        self.tts_voice_add_btn.setMaximumWidth(40)
        self.tts_voice_add_btn.setToolTip(
            "VOICEVOX 음성 추가/편집 — 가동 중인 엔진에서 전체 목록을 받아와 선택"
        )
        self.tts_voice_add_btn.clicked.connect(self._open_voicevox_picker)
        self.tts_sample_ja_btn = QtWidgets.QPushButton("▶")
        self.tts_sample_ja_btn.setObjectName("settingsSecondaryButton")
        self.tts_sample_ja_btn.setMaximumWidth(40)
        self.tts_sample_ja_btn.setToolTip(f"샘플 재생: \"{SAMPLE_TEXT_JA}\"")
        self.tts_engine_ja_combo.currentIndexChanged.connect(
            lambda *_: self._refresh_voices("ja")
        )
        self.tts_engine_ja_combo.currentIndexChanged.connect(
            lambda *_: self._refresh_voice_add_visibility()
        )
        self.tts_sample_ja_btn.clicked.connect(lambda: self._play_sample("ja"))

        ja_row = QtWidgets.QWidget()
        ja_layout = QtWidgets.QHBoxLayout(ja_row)
        ja_layout.setContentsMargins(0, 0, 0, 0)
        ja_layout.addWidget(self.tts_voice_ja_combo, 1)
        ja_layout.addWidget(self.tts_voice_add_btn)
        ja_layout.addWidget(self.tts_sample_ja_btn)

        self.tts_license_label = _muted_label("")
        self.tts_clear_cache_btn = QtWidgets.QPushButton("TTS 캐시 비우기")
        self.tts_clear_cache_btn.setObjectName("settingsSecondaryButton")
        self.tts_clear_cache_btn.clicked.connect(self._clear_tts_cache)
        self.tts_cache_status = QtWidgets.QLabel("")
        self.tts_cache_status.setObjectName("settingsStatus")
        set_status_state(self.tts_cache_status, "muted")

        layout.addRow("", self.tts_enabled_check)
        layout.addRow("", self.tts_play_front_check)
        layout.addRow("", self.tts_play_back_check)
        layout.addRow("", self.tts_play_examples_check)
        layout.addRow("", self.tts_pre_generate_check)
        self._add_form_row(layout, "영어 엔진", self.tts_engine_en_combo)
        self._add_form_row(layout, "영어 음성", en_row)
        self._add_form_row(layout, "일본어 엔진", self.tts_engine_ja_combo)
        self._add_form_row(layout, "일본어 음성", ja_row)
        layout.addRow(self.tts_license_label)
        cache_row = QtWidgets.QWidget()
        cache_layout = QtWidgets.QHBoxLayout(cache_row)
        cache_layout.setContentsMargins(0, 0, 0, 0)
        cache_layout.addWidget(self.tts_clear_cache_btn)
        cache_layout.addWidget(self.tts_cache_status, 1)
        layout.addRow("", cache_row)
        return page

    def _add_form_row(
        self,
        layout: QtWidgets.QFormLayout,
        label_text: str,
        field: QtWidgets.QWidget,
    ) -> None:
        label = QtWidgets.QLabel(label_text)
        label.setObjectName("settingsFormLabel")
        label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        layout.addRow(label, field)
