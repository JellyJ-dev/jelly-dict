from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.storage import secret_store
from app.storage.settings_store import Settings, SettingsStore
from app.ui.dialog_buttons import configure_footer_button
from app.ui.dialog_shortcuts import install_standard_close_shortcut
from app.ui.widgets.pill_scrollbar import install_pill_scrollbars


SAMPLE_TEXT_EN = "apple"
SAMPLE_TEXT_JA = "りんご"

VOICEVOX_DOWNLOAD_URL = "https://voicevox.hiroshiba.jp/"
EDGE_TTS_INSTALL_HINT = "pipx install edge-tts"


def _settings_combo() -> QtWidgets.QComboBox:
    combo = QtWidgets.QComboBox()
    combo.setObjectName("settingsCombo")
    view = QtWidgets.QListView(combo)
    view.setObjectName("settingsComboPopup")
    view.setFrameShape(QtWidgets.QFrame.NoFrame)
    view.setUniformItemSizes(True)
    palette = view.palette()
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#30302d"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#e8744f"))
    view.setPalette(palette)
    combo.setView(view)
    return combo


class _SettingsStatusWorker(QtCore.QObject):
    finished = QtCore.Signal(object)

    @QtCore.Slot()
    def run(self) -> None:
        status = {
            "gv_key_set": False,
            "kokoro_available": False,
            "edge_available": False,
            "brew_available": False,
            "kokoro_cache_mb": 0.0,
        }
        try:
            status["gv_key_set"] = secret_store.is_set("google_vision_api_key")
        except Exception:
            status["gv_key_set"] = False
        try:
            from app.anki.tts import get_provider_info
            from app.ui.tts_install_worker import brew_available, kokoro_model_cache_size

            status["kokoro_available"] = bool(get_provider_info("kokoro").available)
            status["edge_available"] = bool(get_provider_info("edge").available)
            status["brew_available"] = bool(brew_available())
            status["kokoro_cache_mb"] = kokoro_model_cache_size() / 1024 / 1024
        except Exception:
            pass
        self.finished.emit(status)


class SettingsDialog(QtWidgets.QDialog):
    settingsChanged = QtCore.Signal(Settings)

    def __init__(
        self,
        store: SettingsStore,
        parent: QtWidgets.QWidget | None = None,
        initial_settings: Settings | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self.setObjectName("settingsDialog")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setWindowTitle("설정")
        self.resize(900, 720)
        self.setMinimumWidth(820)
        self._sample_player = None
        self._install_thread: QtCore.QThread | None = None
        self._sample_thread: QtCore.QThread | None = None
        self._network_test_thread: QtCore.QThread | None = None
        self._network_test_worker: QtCore.QObject | None = None
        self._status_thread: QtCore.QThread | None = None
        self._status_worker: _SettingsStatusWorker | None = None
        self._status_probe_timer = QtCore.QTimer(self)
        self._status_probe_timer.setSingleShot(True)
        self._status_probe_timer.timeout.connect(self._start_status_probe)
        # Keep TTS provider instances alive across clicks so the heavy
        # KPipeline (~327MB torch.load) is built only once per session.
        self._tts_provider_cache: dict[str, object] = {}
        install_standard_close_shortcut(self)
        self._build_ui()
        self._load(initial_settings or store.load())
        self._status_probe_timer.start(0)

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
        self.gv_key_status.setStyleSheet("color: #aaa59c;")
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
        self.ankiconnect_status.setStyleSheet("color: #888;")
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
        self.tts_cache_status.setStyleSheet("color: #aaa59c;")

        layout.addRow("", self.tts_enabled_check)
        layout.addRow("", self.tts_play_front_check)
        layout.addRow("", self.tts_play_back_check)
        layout.addRow("", self.tts_play_examples_check)
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

    # ── engine combos ──────────────────────────────────────────────
    def _populate_engine_combo(self, combo: QtWidgets.QComboBox, language: str) -> None:
        from app.anki.tts import list_provider_classes

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("사용 안 함", "none")
        for name, cls in list_provider_classes().items():
            info = cls.info()
            voices = info.voices_ja if language == "ja" else info.voices_en
            if not voices:
                continue
            label = info.display_name
            if not info.available:
                label = f"{label} (미설치)"
            combo.addItem(label, name)
        combo.blockSignals(False)

    def _refresh_voices(self, language: str) -> None:
        if language == "en":
            engine_combo = self.tts_engine_en_combo
            voice_combo = self.tts_voice_en_combo
        else:
            engine_combo = self.tts_engine_ja_combo
            voice_combo = self.tts_voice_ja_combo
        name = engine_combo.currentData()
        voice_combo.blockSignals(True)
        voice_combo.clear()
        if name and name != "none":
            voices = self._voices_for(name, language)
            for v in voices:
                voice_combo.addItem(self._voice_display_label(name, v), v)
        voice_combo.blockSignals(False)
        self._refresh_license_label()

    def _voice_display_label(self, engine: str, voice: str) -> str:
        if engine == "voicevox":
            from app.anki.tts.voicevox_provider import display_label
            return display_label(voice)
        return voice

    def _refresh_voice_add_visibility(self) -> None:
        """Show the '+' picker only when VOICEVOX is the JA engine."""
        is_voicevox = self.tts_engine_ja_combo.currentData() == "voicevox"
        self.tts_voice_add_btn.setVisible(is_voicevox)

    def _open_voicevox_picker(self) -> None:
        from app.anki.tts.voicevox_provider import VoicevoxProvider

        if not VoicevoxProvider.is_running():
            self.tts_license_label.setText(
                "VOICEVOX 엔진이 가동 중이 아닙니다. 앱을 실행한 뒤 다시 시도하세요."
            )
            return

        settings = self._store.load()
        all_voices = VoicevoxProvider.fetch_voices(settings.voicevox_url)
        if not all_voices:
            self.tts_license_label.setText("VOICEVOX 음성 목록을 불러오지 못했습니다.")
            return

        current = set(settings.tts_voicevox_voices)
        dlg = _VoicevoxVoicePicker(all_voices, current, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        chosen = dlg.selected()
        if not chosen:
            return
        # Persist and refresh the JA voice combo so the new selection is
        # visible immediately.
        self._store.update(tts_voicevox_voices=chosen)
        self._refresh_voices("ja")

    def _voices_for(self, engine: str, language: str) -> tuple[str, ...]:
        """Per-engine voice list — for VOICEVOX, return the user's saved
        curated list (defaults to the 5 standard voices). The "+" button
        lets the user pull from the live engine catalog."""
        from app.anki.tts import get_provider_info

        if engine == "voicevox" and language == "ja":
            settings = self._store.load()
            return tuple(settings.tts_voicevox_voices) or ()
        info = get_provider_info(engine)
        return info.voices_ja if language == "ja" else info.voices_en

    def _refresh_license_label(self) -> None:
        from app.anki.tts import get_provider_info

        notes: list[str] = []
        for combo, lang in (
            (self.tts_engine_en_combo, "EN"),
            (self.tts_engine_ja_combo, "JA"),
        ):
            name = combo.currentData()
            if not name or name == "none":
                continue
            info = get_provider_info(name)
            line = f"{lang} {info.display_name} — {info.license_note}"
            if info.usage_warning:
                line += f"  ⚠ {info.usage_warning}"
            notes.append(line)
        self.tts_license_label.setText("\n".join(notes))

    def _make_uninstall_btn(self, engine_name: str, tooltip: str, handler) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton("")
        btn.setObjectName("settingsSecondaryButton")
        btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
        btn.setIconSize(QtCore.QSize(15, 15))
        btn.setMaximumWidth(40)
        btn.setToolTip(f"{engine_name} 삭제 — {tooltip}")
        btn.clicked.connect(handler)
        btn.hide()
        return btn

    def _refresh_install_status(self) -> None:
        from app.anki.tts import get_provider_info
        from app.ui.tts_install_worker import (
            brew_available, kokoro_model_cache_size,
        )

        kokoro = get_provider_info("kokoro")
        edge = get_provider_info("edge")
        self._apply_install_status(
            kokoro_available=kokoro.available,
            edge_available=edge.available,
            brew_is_available=brew_available(),
            kokoro_cache_mb=kokoro_model_cache_size() / 1024 / 1024,
        )

    def _apply_install_status(
        self,
        *,
        kokoro_available: bool,
        edge_available: bool,
        brew_is_available: bool,
        kokoro_cache_mb: float,
    ) -> None:
        if kokoro_available:
            self.tts_install_btn.setEnabled(False)
            self.tts_install_btn.setText("Kokoro ✓")
            self.kokoro_uninstall_btn.show()
            if kokoro_cache_mb > 1:
                self.kokoro_uninstall_btn.setToolTip(
                    f"Kokoro 삭제 — 패키지 + 모델 캐시(~{kokoro_cache_mb:.0f}MB) 정리"
                )
        else:
            self.tts_install_btn.setEnabled(True)
            self.tts_install_btn.setText("Kokoro 설치")
            self.kokoro_uninstall_btn.hide()

        # VOICEVOX never runs through brew (no cask exists) — always
        # surfaces the download page, so be upfront about it.
        self.voicevox_install_btn.setText("VOICEVOX 다운로드")
        # We can't reliably tell whether VOICEVOX is installed (it could
        # be a brew cask, a manual /Applications drop, or absent), so the
        # uninstall button is always available when brew is around — its
        # worker reports gracefully if there's nothing to uninstall.
        self.voicevox_uninstall_btn.setVisible(brew_is_available)

        if edge_available:
            self.edge_install_btn.setEnabled(False)
            self.edge_install_btn.setText("edge-tts ✓")
            self.edge_uninstall_btn.show()
        else:
            self.edge_install_btn.setEnabled(True)
            self.edge_install_btn.setText("edge-tts 설치")
            self.edge_uninstall_btn.hide()
        self.tts_install_status.setText("")

    # ── load / save ────────────────────────────────────────────────
    def _load(self, settings: Settings) -> None:
        self.excel_dir.set_path(settings.default_excel_dir)
        self.excel_en.set_path(settings.excel_path_en or settings.excel_path_for("en"))
        self.excel_ja.set_path(settings.excel_path_ja or settings.excel_path_for("ja"))
        self.anki_dir.set_path(settings.default_anki_export_dir)
        self.anki_en.set_path(settings.anki_path_en or settings.anki_path_for("en"))
        self.anki_ja.set_path(settings.anki_path_ja or settings.anki_path_for("ja"))
        self.delay.setValue(settings.request_delay_seconds)
        self.cache_check.setChecked(settings.cache_enabled)
        self.preview_check.setChecked(settings.show_preview)
        idx = self.dup_combo.findData(settings.duplicate_policy)
        if idx >= 0:
            self.dup_combo.setCurrentIndex(idx)
        self.deck_name.setText(settings.default_deck_name)
        idx = self.provider_combo.findData(settings.provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.ankiconnect_check.setChecked(settings.ankiconnect_enabled)
        self.ankiconnect_url.setText(settings.ankiconnect_url)

        idx = self.ocr_combo.findData(getattr(settings, "ocr_provider", "apple_vision"))
        if idx >= 0:
            self.ocr_combo.setCurrentIndex(idx)
        self.gv_key_status.setStyleSheet("color: #aaa59c;")
        self.gv_key_status.setText("키 상태 확인 중…")

        self.tts_enabled_check.setChecked(settings.tts_enabled)
        self.tts_play_front_check.setChecked(settings.tts_play_front)
        self.tts_play_back_check.setChecked(settings.tts_play_back)
        self.tts_play_examples_check.setChecked(settings.tts_play_examples)

        self._populate_engine_combo(self.tts_engine_en_combo, "en")
        self._populate_engine_combo(self.tts_engine_ja_combo, "ja")
        idx = self.tts_engine_en_combo.findData(settings.tts_engine_en)
        if idx >= 0:
            self.tts_engine_en_combo.setCurrentIndex(idx)
        idx = self.tts_engine_ja_combo.findData(settings.tts_engine_ja)
        if idx >= 0:
            self.tts_engine_ja_combo.setCurrentIndex(idx)
        self._refresh_voices("en")
        self._refresh_voices("ja")
        idx = self.tts_voice_en_combo.findData(settings.tts_voice_en)
        if idx >= 0:
            self.tts_voice_en_combo.setCurrentIndex(idx)
        idx = self.tts_voice_ja_combo.findData(settings.tts_voice_ja)
        if idx >= 0:
            self.tts_voice_ja_combo.setCurrentIndex(idx)
        self.tts_install_status.setText("설치 상태 확인 중…")
        self._refresh_voice_add_visibility()

    def _start_status_probe(self) -> None:
        if self._status_thread is not None:
            return
        thread = QtCore.QThread(self)
        worker = _SettingsStatusWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_status_probe_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_status_probe)
        self._status_thread = thread
        self._status_worker = worker
        thread.start()

    @QtCore.Slot(object)
    def _on_status_probe_finished(self, status_obj: object) -> None:
        status = status_obj if isinstance(status_obj, dict) else {}
        self._apply_gv_key_status(bool(status.get("gv_key_set", False)))
        self._apply_install_status(
            kokoro_available=bool(status.get("kokoro_available", False)),
            edge_available=bool(status.get("edge_available", False)),
            brew_is_available=bool(status.get("brew_available", False)),
            kokoro_cache_mb=float(status.get("kokoro_cache_mb", 0.0) or 0.0),
        )

    @QtCore.Slot()
    def _clear_status_probe(self) -> None:
        self._status_thread = None
        self._status_worker = None

    def _save(self) -> None:
        if not self._ready_for_close_or_save():
            return
        en_engine = self.tts_engine_en_combo.currentData() or "none"
        ja_engine = self.tts_engine_ja_combo.currentData() or "none"
        en_voice = self.tts_voice_en_combo.currentData() or ""
        ja_voice = self.tts_voice_ja_combo.currentData() or ""
        updated = self._store.update(
            default_excel_dir=self.excel_dir.path() or "",
            excel_path_en=self.excel_en.path() or "",
            excel_path_ja=self.excel_ja.path() or "",
            default_anki_export_dir=self.anki_dir.path() or "",
            anki_path_en=self.anki_en.path() or "",
            anki_path_ja=self.anki_ja.path() or "",
            request_delay_seconds=float(self.delay.value()),
            cache_enabled=self.cache_check.isChecked(),
            show_preview=self.preview_check.isChecked(),
            duplicate_policy=self.dup_combo.currentData(),
            default_deck_name=self.deck_name.text().strip() or "JellyDict",
            provider=self.provider_combo.currentData(),
            ankiconnect_enabled=self.ankiconnect_check.isChecked(),
            ankiconnect_url=self.ankiconnect_url.text().strip() or "http://127.0.0.1:8765",
            ocr_provider=self.ocr_combo.currentData() or "apple_vision",
            tts_enabled=self.tts_enabled_check.isChecked(),
            tts_play_front=self.tts_play_front_check.isChecked(),
            tts_play_back=self.tts_play_back_check.isChecked(),
            tts_play_examples=self.tts_play_examples_check.isChecked(),
            tts_engine_en=en_engine,
            tts_engine_ja=ja_engine,
            tts_voice_en=en_voice,
            tts_voice_ja=ja_voice,
        )
        self.settingsChanged.emit(updated)
        self._wait_for_status_probe()
        self.accept()

    # ── AnkiConnect ────────────────────────────────────────────────
    def _test_ankiconnect(self) -> None:
        url = self.ankiconnect_url.text().strip() or "http://127.0.0.1:8765"
        worker = _AnkiConnectTestWorker(url)
        if not self._run_network_test(worker, self._on_ankiconnect_test_finished):
            return
        self.ankiconnect_test_btn.setEnabled(False)
        self.ankiconnect_status.setStyleSheet("color: #888;")
        self.ankiconnect_status.setText("연결 테스트 중…")

    @QtCore.Slot(bool, str)
    def _on_ankiconnect_test_finished(self, ok: bool, message: str) -> None:
        self.ankiconnect_test_btn.setEnabled(True)
        if ok:
            self.ankiconnect_status.setStyleSheet("color: #2a8;")
            self.ankiconnect_status.setText("✓ 연결됨")
        else:
            self.ankiconnect_status.setStyleSheet("color: #d33;")
            self.ankiconnect_status.setText(message or "응답 없음")

    # ── Google Vision API key ──────────────────────────────────────
    def _refresh_gv_key_status(self) -> None:
        self._apply_gv_key_status(secret_store.is_set("google_vision_api_key"))

    def _apply_gv_key_status(self, is_set: bool) -> None:
        if is_set:
            self.gv_key_status.setStyleSheet("color: #2a8;")
            self.gv_key_status.setText("✓ Keychain에 저장됨")
        else:
            self.gv_key_status.setStyleSheet("color: #aaa59c;")
            self.gv_key_status.setText("저장된 키가 없습니다")

    def _save_gv_key(self) -> None:
        value = self.gv_key_edit.text().strip()
        if not value:
            self.gv_key_status.setStyleSheet("color: #d33;")
            self.gv_key_status.setText("키를 입력하세요")
            return
        try:
            secret_store.set("google_vision_api_key", value)
        except Exception as exc:
            self.gv_key_status.setStyleSheet("color: #d33;")
            self.gv_key_status.setText(f"저장 실패: {type(exc).__name__}")
            return
        self.gv_key_edit.clear()
        self._refresh_gv_key_status()

    def _clear_gv_key(self) -> None:
        secret_store.delete("google_vision_api_key")
        self.gv_key_edit.clear()
        self._refresh_gv_key_status()

    def _test_gv_key(self) -> None:
        key = secret_store.get("google_vision_api_key")
        if not key:
            self.gv_key_status.setStyleSheet("color: #d33;")
            self.gv_key_status.setText("키 미설정")
            return
        settings = self._store.load()
        worker = _GoogleVisionKeyTestWorker(key, settings.google_vision_endpoint)
        if not self._run_network_test(worker, self._on_gv_key_test_finished):
            return
        self.gv_key_test_btn.setEnabled(False)
        self.gv_key_status.setStyleSheet("color: #aaa59c;")
        self.gv_key_status.setText("키 테스트 중…")

    @QtCore.Slot(bool, str)
    def _on_gv_key_test_finished(self, ok: bool, message: str) -> None:
        self.gv_key_test_btn.setEnabled(True)
        if not ok:
            self.gv_key_status.setStyleSheet("color: #d33;")
            self.gv_key_status.setText(message or "키 테스트 실패")
            return
        self.gv_key_status.setStyleSheet("color: #2a8;")
        self.gv_key_status.setText("✓ 키가 정상입니다")

    def _run_network_test(self, worker: QtCore.QObject, finished_slot) -> bool:
        if self._is_network_test_running():
            self._set_busy_test_message()
            return False

        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)  # type: ignore[attr-defined]
        worker.finished.connect(finished_slot)  # type: ignore[attr-defined]
        worker.finished.connect(thread.quit)  # type: ignore[attr-defined]
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_network_test)
        self._network_test_thread = thread
        self._network_test_worker = worker
        thread.start()
        return True

    def _is_network_test_running(self) -> bool:
        if self._network_test_thread is None:
            return False
        try:
            return self._network_test_thread.isRunning()
        except RuntimeError:
            self._clear_network_test()
            return False

    @QtCore.Slot()
    def _clear_network_test(self) -> None:
        self._network_test_thread = None
        self._network_test_worker = None

    def _set_busy_test_message(self) -> None:
        self.ankiconnect_status.setStyleSheet("color: #d33;")
        self.gv_key_status.setStyleSheet("color: #d33;")
        self.ankiconnect_status.setText("진행 중인 테스트가 끝난 뒤 다시 시도하세요.")
        self.gv_key_status.setText("진행 중인 테스트가 끝난 뒤 다시 시도하세요.")

    def _is_install_running(self) -> bool:
        if self._install_thread is None:
            return False
        try:
            return self._install_thread.isRunning()
        except RuntimeError:
            self._install_thread = None
            return False

    def _is_sample_running(self) -> bool:
        if self._sample_thread is None:
            return False
        try:
            return self._sample_thread.isRunning()
        except RuntimeError:
            self._sample_thread = None
            return False

    def _set_busy_tts_message(self, *, sample: bool = False) -> None:
        self.tabs.setCurrentIndex(2)
        if sample:
            self.tts_license_label.setText("샘플 생성이 끝난 뒤 다시 시도하세요.")
            return
        self.tts_install_status.setText("설치/삭제 작업이 끝난 뒤 다시 시도하세요.")

    def _ready_for_close_or_save(self) -> bool:
        if self._is_network_test_running():
            self._set_busy_test_message()
            return False
        if self._is_install_running():
            self._set_busy_tts_message()
            return False
        if self._is_sample_running():
            self._set_busy_tts_message(sample=True)
            return False
        return True

    def _is_status_probe_running(self) -> bool:
        if self._status_thread is None:
            return False
        try:
            return self._status_thread.isRunning()
        except RuntimeError:
            self._clear_status_probe()
            return False

    def _wait_for_status_probe(self) -> None:
        if self._status_probe_timer.isActive():
            self._status_probe_timer.stop()
        if self._status_thread is None:
            return
        try:
            if self._status_thread.isRunning():
                self._status_thread.quit()
                self._status_thread.wait(1200)
        except RuntimeError:
            pass
        self._clear_status_probe()

    def reject(self) -> None:
        if not self._ready_for_close_or_save():
            return
        self._wait_for_status_probe()
        super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self._ready_for_close_or_save():
            event.ignore()
            return
        self._wait_for_status_probe()
        super().closeEvent(event)

    # ── TTS install / sample / cache ───────────────────────────────
    def _install_engine(self, name: str) -> None:
        """Run the install worker for ``name`` (kokoro|voicevox|edge)."""
        if self._install_thread is not None:
            return
        from app.ui.tts_install_worker import (
            KokoroInstallWorker, VoicevoxInstallWorker, EdgeTtsInstallWorker,
        )

        worker_cls = {
            "kokoro": KokoroInstallWorker,
            "voicevox": VoicevoxInstallWorker,
            "edge": EdgeTtsInstallWorker,
        }.get(name)
        if worker_cls is None:
            return

        for btn in (
            self.tts_install_btn, self.voicevox_install_btn, self.edge_install_btn,
        ):
            btn.setEnabled(False)
        self.tts_install_status.setText(f"{name} 설치 시작 — 수십 초~수 분 걸릴 수 있습니다.")

        self._install_thread = QtCore.QThread(self)
        worker = worker_cls()
        worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(worker.run)
        worker.progress.connect(self.tts_install_status.setText)
        worker.open_url.connect(
            lambda url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        )
        worker.finished.connect(lambda ok, msg: self._on_install_finished(ok, msg, worker))
        self._install_thread.start()

    def _on_install_finished(self, ok: bool, msg: str, worker) -> None:
        self.tts_install_status.setText(msg)
        if self._install_thread is not None:
            self._install_thread.quit()
            self._install_thread.wait()
            self._install_thread = None
        worker.deleteLater()
        # Drop any cached providers — installs/uninstalls invalidate them.
        self._tts_provider_cache.clear()
        # Re-import to pick up freshly installed packages.
        try:
            import sys
            for name in list(sys.modules):
                if name.startswith("kokoro") or name == "soundfile":
                    del sys.modules[name]
        except Exception:
            pass
        current_en = self.tts_engine_en_combo.currentData()
        current_ja = self.tts_engine_ja_combo.currentData()
        self._populate_engine_combo(self.tts_engine_en_combo, "en")
        self._populate_engine_combo(self.tts_engine_ja_combo, "ja")
        for combo, val in (
            (self.tts_engine_en_combo, current_en),
            (self.tts_engine_ja_combo, current_ja),
        ):
            idx = combo.findData(val)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self._refresh_voices("en")
        self._refresh_voices("ja")
        self._refresh_install_status()

    def _uninstall_engine(self, name: str) -> None:
        """Run an uninstall worker after a confirmation dialog."""
        if self._install_thread is not None:
            return
        from app.ui.tts_install_worker import (
            KokoroUninstallWorker, VoicevoxUninstallWorker, EdgeTtsUninstallWorker,
            kokoro_model_cache_size,
        )

        worker_cls = {
            "kokoro": KokoroUninstallWorker,
            "voicevox": VoicevoxUninstallWorker,
            "edge": EdgeTtsUninstallWorker,
        }.get(name)
        if worker_cls is None:
            return

        if name == "kokoro":
            cache_mb = kokoro_model_cache_size() / 1024 / 1024
            detail = (
                f"Kokoro 패키지 (kokoro, soundfile)와 모델 캐시 "
                f"(~{cache_mb:.0f}MB)를 삭제합니다.\n\n"
                "torch / numpy 같은 공유 의존성은 다른 프로그램에서 쓰일 수 "
                "있어 함께 삭제하지 않습니다."
            )
        elif name == "voicevox":
            detail = "Homebrew로 설치한 VOICEVOX 앱을 삭제합니다."
        else:
            detail = "pipx로 설치된 edge-tts를 삭제합니다."

        reply = QtWidgets.QMessageBox.question(
            self,
            "삭제 확인",
            detail,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        for btn in (
            self.tts_install_btn, self.voicevox_install_btn, self.edge_install_btn,
            self.kokoro_uninstall_btn, self.voicevox_uninstall_btn,
            self.edge_uninstall_btn,
        ):
            btn.setEnabled(False)
        self.tts_install_status.setText(f"{name} 삭제 중…")

        self._install_thread = QtCore.QThread(self)
        worker = worker_cls()
        worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(worker.run)
        worker.progress.connect(self.tts_install_status.setText)
        worker.finished.connect(lambda ok, msg: self._on_install_finished(ok, msg, worker))
        self._install_thread.start()

    def _install_or_open_voicevox(self) -> None:
        from app.ui.tts_install_worker import brew_available

        if brew_available():
            self._install_engine("voicevox")
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(VOICEVOX_DOWNLOAD_URL))
            self.tts_install_status.setText(
                "Homebrew가 없어 VOICEVOX 다운로드 페이지를 열었습니다."
            )

    def _install_or_copy_edge(self) -> None:
        from app.ui.tts_install_worker import brew_available, pipx_available

        if pipx_available() or brew_available():
            self._install_engine("edge")
        else:
            QtWidgets.QApplication.clipboard().setText(EDGE_TTS_INSTALL_HINT)
            self.tts_install_status.setText(
                f"pipx/brew가 없어 명령을 복사했습니다: {EDGE_TTS_INSTALL_HINT}"
            )

    def _play_sample(self, language: str) -> None:
        from app.anki.tts.cache import cache_path

        if language == "en":
            engine = self.tts_engine_en_combo.currentData()
            voice = self.tts_voice_en_combo.currentData()
            text = SAMPLE_TEXT_EN
            btn = self.tts_sample_en_btn
        else:
            engine = self.tts_engine_ja_combo.currentData()
            voice = self.tts_voice_ja_combo.currentData()
            text = SAMPLE_TEXT_JA
            btn = self.tts_sample_ja_btn

        if not engine or engine == "none" or not voice:
            self.tts_license_label.setText("샘플 재생 전 엔진/음성을 선택하세요.")
            return

        settings = self._store.load()
        settings.tts_engine_en = self.tts_engine_en_combo.currentData() or "none"
        settings.tts_engine_ja = self.tts_engine_ja_combo.currentData() or "none"
        settings.tts_voice_en = self.tts_voice_en_combo.currentData() or ""
        settings.tts_voice_ja = self.tts_voice_ja_combo.currentData() or ""

        out_path = cache_path(
            language,
            engine,
            voice,
            text,
            bitrate=getattr(settings, "tts_bitrate", ""),
            sample_rate=getattr(settings, "tts_sample_rate", None),
        )
        if out_path.exists():
            self._play_audio_file(out_path)
            return

        # First time for this (engine, voice) — synthesis happens on a
        # background thread because Kokoro's first call downloads a
        # ~327MB model and warms torch, which would freeze the UI.
        if getattr(self, "_sample_thread", None) is not None:
            return
        btn.setEnabled(False)
        btn.setText("…")

        # Be honest about what's about to happen — Kokoro pulls the
        # model weights from HuggingFace on first use.
        if engine == "kokoro":
            from app.ui.tts_install_worker import kokoro_model_cache_size

            if kokoro_model_cache_size() < 100 * 1024 * 1024:  # < 100MB → not cached yet
                self.tts_license_label.setText(
                    "Kokoro 모델 가중치를 처음 1회 다운로드합니다 (~330MB). "
                    "다음부터는 캐시에서 즉시 재생됩니다."
                )
            else:
                self.tts_license_label.setText("샘플 생성 중…")
        else:
            self.tts_license_label.setText("샘플 생성 중…")

        # Reuse the provider across clicks so KPipeline isn't rebuilt
        # (torch.load of the 327MB .pth is the dominant cost).
        provider = self._tts_provider_cache.get(engine)
        if provider is None:
            from app.anki.tts import build_provider

            provider = build_provider(engine, settings)
            self._tts_provider_cache[engine] = provider

        self._sample_thread = QtCore.QThread(self)
        worker = _SampleSynthWorker(provider, language, voice, text, out_path)
        worker.moveToThread(self._sample_thread)
        self._sample_thread.started.connect(worker.run)
        worker.finished.connect(
            lambda ok, msg, path: self._on_sample_finished(ok, msg, path, btn, worker)
        )
        self._sample_thread.start()

    def _on_sample_finished(self, ok, msg, path, btn, worker) -> None:
        btn.setEnabled(True)
        btn.setText("▶")
        if self._sample_thread is not None:
            self._sample_thread.quit()
            self._sample_thread.wait()
            self._sample_thread = None
        worker.deleteLater()
        if ok and path is not None:
            self.tts_license_label.setText("")
            self._play_audio_file(path)
            self._refresh_license_label()
        else:
            self.tts_license_label.setText(msg or "샘플 생성 실패")

    def _play_audio_file(self, path: Path) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        player = QMediaPlayer(self)
        audio_out = QAudioOutput(self)
        player.setAudioOutput(audio_out)
        player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        player.play()
        self._sample_player = (player, audio_out)

    def _clear_tts_cache(self) -> None:
        from app.anki.tts.cache import clear_cache

        n = clear_cache()
        self.tts_cache_status.setText(f"{n}개 파일 삭제됨")


class _SampleSynthWorker(QtCore.QObject):
    """Run TTS synthesis off the UI thread.

    The provider is passed in pre-built so its KPipeline / model state
    persists across clicks — only the first call within a dialog session
    pays the heavy ``torch.load`` cost.
    """

    finished = QtCore.Signal(bool, str, object)  # ok, error_msg, Path|None

    def __init__(self, provider, language, voice, text, out_path) -> None:
        super().__init__()
        self._provider = provider
        self._language = language
        self._voice = voice
        self._text = text
        self._out_path = out_path

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self._provider.synthesize(
                self._text,
                language=self._language,
                voice=self._voice,
                out_path=self._out_path,
            )
        except Exception as exc:
            self.finished.emit(False, f"{type(exc).__name__}: {exc}", None)
            return
        self.finished.emit(True, "", self._out_path)


class _AnkiConnectTestWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    @QtCore.Slot()
    def run(self) -> None:
        try:
            from app.anki.ankiconnect_client import AnkiConnectClient

            ok = AnkiConnectClient(self._url).is_available()
        except Exception as exc:
            self.finished.emit(False, f"연결 실패: {exc}")
            return
        self.finished.emit(ok, "" if ok else "응답 없음")


class _GoogleVisionKeyTestWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)

    def __init__(self, api_key: str, endpoint: str) -> None:
        super().__init__()
        self._api_key = api_key
        self._endpoint = endpoint

    @QtCore.Slot()
    def run(self) -> None:
        try:
            from app.ocr.google_vision import test_api_key

            test_api_key(self._api_key, self._endpoint)
        except Exception as exc:
            self.finished.emit(False, str(exc) or type(exc).__name__)
            return
        self.finished.emit(True, "")


class _VoicevoxVoicePicker(QtWidgets.QDialog):
    """Multi-select dialog for VOICEVOX speaker/style entries.

    The list is fetched live from the engine. Users can search by typing
    and check exactly the voices they want kept in their voice combo.
    Returning order matches the visible (sorted) order so the curated
    favorites stay near the top of the dropdown.
    """

    def __init__(
        self,
        all_voices: tuple[str, ...],
        already_selected: set[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setWindowTitle("VOICEVOX 음성 선택")
        self.resize(520, 600)
        self._all_voices = all_voices
        self._initial = already_selected
        install_standard_close_shortcut(self)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("settingsLineEdit")
        self.search.setPlaceholderText("이름 / 스타일 / ID로 필터링…")
        self.search.textChanged.connect(self._apply_filter)
        root.addWidget(self.search)

        from app.anki.tts.voicevox_provider import display_label

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("settingsVoiceList")
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for voice in all_voices:
            item = QtWidgets.QListWidgetItem(display_label(voice))
            item.setData(QtCore.Qt.UserRole, voice)  # canonical, no Korean
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked if voice in already_selected else QtCore.Qt.Unchecked
            )
            self.list_widget.addItem(item)
        root.addWidget(self.list_widget, 1)

        info = _muted_label(
            "✓ 체크된 음성만 일본어 음성 콤보에 표시됩니다. 체크 순서가 아닌 "
            "VOICEVOX의 ID 순서대로 정렬됩니다."
        )
        root.addWidget(info)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        ok_btn = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        if ok_btn is not None:
            configure_footer_button(ok_btn, role="primary", text="저장")
        if cancel_btn is not None:
            configure_footer_button(cancel_btn, role="secondary", text="취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _apply_filter(self, query: str) -> None:
        q = query.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(bool(q) and q not in item.text().lower())

    def selected(self) -> list[str]:
        out: list[str] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                out.append(item.data(QtCore.Qt.UserRole) or item.text())
        return out


def _section_header(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("settingsSectionHeader")
    label.setStyleSheet(
        "font-weight: 600; color: #e7e1d6; padding: 12px 0 4px 0;"
        "border-top: 1px solid #3f3f3c; margin-top: 8px;"
    )
    return label


def _muted_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("settingsMutedLabel")
    label.setWordWrap(True)
    label.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
    label.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
    )
    label.setStyleSheet(
        "color: #aaa59c; font-size: 12px; padding: 4px 0;"
    )
    return label


class _PathPicker(QtWidgets.QWidget):
    def __init__(self, mode: str = "dir", file_filter: str = "", parent=None) -> None:
        """mode: 'dir' | 'file_save' | 'file_open'"""
        super().__init__(parent)
        self._mode = mode
        self._filter = file_filter
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.line = QtWidgets.QLineEdit()
        self.line.setObjectName("settingsPathLine")
        self.line.setMinimumWidth(520)
        self.button = QtWidgets.QPushButton("선택…")
        self.button.setObjectName("settingsSecondaryButton")
        self.button.setMaximumWidth(68)
        self.button.setMinimumHeight(38)
        layout.addWidget(self.line, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self._pick)

    def _pick(self) -> None:
        current = self.line.text()
        if self._mode == "dir":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "폴더 선택", current)
        elif self._mode == "file_open":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "기존 파일 선택", current, self._filter
            )
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "저장할 파일 선택 / 새로 만들기", current, self._filter
            )
        if path:
            self.line.setText(path)

    def path(self) -> str:
        return self.line.text().strip()

    def set_path(self, path: str) -> None:
        self.line.setText(path or "")
