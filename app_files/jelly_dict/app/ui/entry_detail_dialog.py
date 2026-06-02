from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlparse

from PySide6 import QtCore, QtGui, QtWidgets

from app.core.models import VocabularyEntry, build_meanings_summary, collect_examples_flat
from app.services.tts_audio_service import cached_audio_path_for_text, tts_configured
from app.services.tts_process_service import synthesize_text_audio_in_process
from app.storage.settings_store import Settings
from app.ui.dialog_shortcuts import install_standard_close_shortcut


class EntryDetailDialog(QtWidgets.QDialog):
    def __init__(
        self,
        entry: VocabularyEntry,
        parent: QtWidgets.QWidget | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        self._settings = settings
        self._tts_thread: QtCore.QThread | None = None
        self._tts_worker: _DetailTtsWorker | None = None
        self._tts_click_enabled = tts_configured(settings, entry.language)
        self._tts_player = None
        self.setObjectName("entryDetailDialog")
        self.setWindowTitle(_primary_form(entry.word) or "단어 상세")
        self.resize(820, 760)
        self.setMinimumSize(640, 560)
        self._build_ui()
        install_standard_close_shortcut(self)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(18)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        header.addStretch(1)
        close_btn = QtWidgets.QPushButton("×")
        close_btn.setObjectName("entryDetailClose")
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)

        title = _TtsTextLabel(_primary_form(self._entry.word), _primary_form(self._entry.word))
        title.setObjectName("entryDetailTitle")
        title.clicked.connect(self._request_tts_for_text)
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setTextFormat(QtCore.Qt.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)

        full_form = (self._entry.word or "").strip()
        primary = _primary_form(full_form)
        if full_form and full_form != primary:
            full_label = _TtsTextLabel(full_form, full_form)
            full_label.setObjectName("entryDetailMeta")
            full_label.clicked.connect(self._request_tts_for_text)
            full_label.setAlignment(QtCore.Qt.AlignCenter)
            full_label.setTextFormat(QtCore.Qt.PlainText)
            full_label.setWordWrap(True)
            layout.addWidget(full_label)

        reading = _primary_form(self._entry.reading or "")
        if reading:
            reading_label = QtWidgets.QLabel(f"[{reading}]")
            reading_label.setObjectName("entryDetailReading")
            reading_label.setAlignment(QtCore.Qt.AlignCenter)
            reading_label.setTextFormat(QtCore.Qt.PlainText)
            reading_label.setWordWrap(True)
            layout.addWidget(reading_label)

        first_gloss = _first_gloss(self._entry)
        if first_gloss:
            summary_label = QtWidgets.QLabel(first_gloss)
            summary_label.setObjectName("entryDetailSummary")
            summary_label.setAlignment(QtCore.Qt.AlignCenter)
            summary_label.setTextFormat(QtCore.Qt.PlainText)
            summary_label.setWordWrap(True)
            layout.addWidget(summary_label)

        meta = []
        if self._entry.part_of_speech:
            meta.append(", ".join(self._entry.part_of_speech))
        if meta:
            meta_label = QtWidgets.QLabel(" · ".join(meta))
            meta_label.setObjectName("entryDetailMeta")
            meta_label.setAlignment(QtCore.Qt.AlignCenter)
            meta_label.setTextFormat(QtCore.Qt.PlainText)
            layout.addWidget(meta_label)

        divider_top = QtWidgets.QFrame()
        divider_top.setObjectName("entryDetailDivider")
        divider_top.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(divider_top)

        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        controls.addStretch(1)
        self.tts_button = QtWidgets.QPushButton("TTS")
        self.tts_button.setObjectName("entryDetailTtsButton")
        self.tts_button.setCheckable(True)
        self.tts_button.setChecked(self._tts_click_enabled)
        self.tts_button.setIcon(_dot_icon(enabled=self._tts_click_enabled))
        self.tts_button.setIconSize(QtCore.QSize(9, 9))
        self.tts_button.clicked.connect(self._on_tts_toggle)
        self._sync_tts_button_state()
        controls.addWidget(self.tts_button)
        layout.addLayout(controls)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("entryDetailScroll")
        body = QtWidgets.QWidget()
        shell_layout = QtWidgets.QVBoxLayout(body)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        card = QtWidgets.QFrame()
        card.setObjectName("entryDetailBodyCard")
        body_layout = QtWidgets.QVBoxLayout(card)
        body_layout.setContentsMargins(22, 20, 22, 22)
        body_layout.setSpacing(14)
        shell_layout.addWidget(card)
        shell_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self._add_meanings(body_layout)
        self._add_examples(body_layout)
        self._add_word_list(body_layout, "동의어", self._entry.synonyms)
        self._add_word_list(body_layout, "반의어", self._entry.antonyms)
        self._add_word_list(body_layout, "태그", self._entry.tags)
        self._add_text_block(body_layout, "메모", self._entry.memo)
        self._add_source(body_layout)
        body_layout.addStretch(1)
        self._tts_toast = _DetailToast(self)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._tts_thread is not None and self._tts_thread.isRunning():
            self._show_tts_message("TTS 생성이 끝난 뒤 닫을 수 있습니다.")
            event.ignore()
            return
        super().closeEvent(event)

    def _sync_tts_button_state(self) -> None:
        configured = tts_configured(self._settings, self._entry.language)
        if not configured:
            self._tts_click_enabled = False
            self.tts_button.setChecked(False)
        else:
            self._tts_click_enabled = self.tts_button.isChecked()
        self.tts_button.setEnabled(True)
        self.tts_button.setIcon(_dot_icon(enabled=configured and self._tts_click_enabled))
        self.tts_button.setToolTip(
            "단어/예문 클릭 재생 활성" if configured and self._tts_click_enabled
            else "단어/예문 클릭 재생 비활성"
        )

    def _on_tts_toggle(self, checked: bool) -> None:
        if not tts_configured(self._settings, self._entry.language):
            self._tts_click_enabled = False
            self.tts_button.setChecked(False)
            self._sync_tts_button_state()
            self._show_tts_message("TTS가 없는 단어입니다.")
            return
        self._tts_click_enabled = checked
        self._sync_tts_button_state()

    @QtCore.Slot(str)
    def _request_tts_for_text(self, text: str) -> None:
        text = (text or "").strip()
        if not self._tts_click_enabled:
            return
        if self._settings is None or self._tts_thread is not None:
            if self._tts_thread is not None:
                self._show_tts_message("TTS 생성 중입니다.")
            return
        if not tts_configured(self._settings, self._entry.language):
            self._sync_tts_button_state()
            self._show_tts_message("TTS가 없는 단어입니다.")
            return
        if not text:
            self._show_tts_message("TTS가 없는 단어입니다.")
            return
        cached = cached_audio_path_for_text(text, self._entry.language, self._settings)
        if cached is not None:
            self._play_audio_file(cached)
            return
        self._tts_thread = QtCore.QThread(self)
        self._tts_worker = _DetailTtsWorker(text, self._entry.language, self._settings)
        self._tts_worker.moveToThread(self._tts_thread)
        self._tts_thread.started.connect(self._tts_worker.run)
        self._tts_worker.finished.connect(self._on_tts_finished)
        self._tts_worker.finished.connect(self._tts_thread.quit)
        self._tts_thread.finished.connect(self._tts_worker.deleteLater)
        self._tts_thread.finished.connect(self._clear_tts_worker)
        self._tts_thread.start()

    @QtCore.Slot(bool, str, object)
    def _on_tts_finished(self, ok: bool, message: str, path_obj: object) -> None:
        self._sync_tts_button_state()
        if ok and isinstance(path_obj, Path):
            self._play_audio_file(path_obj)
            return
        self._show_tts_message(message or "TTS가 없는 단어입니다.")

    @QtCore.Slot()
    def _clear_tts_worker(self) -> None:
        self._tts_thread = None
        self._tts_worker = None

    def _play_audio_file(self, path: Path) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            self.tts_button.setToolTip("QtMultimedia를 사용할 수 없습니다.")
            return
        player = QMediaPlayer(self)
        audio_out = QAudioOutput(self)
        player.setAudioOutput(audio_out)
        player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        player.play()
        self._tts_player = (player, audio_out)

    def _show_tts_message(self, message: str) -> None:
        self._tts_toast.show_message(message)

    def _add_meanings(self, layout: QtWidgets.QVBoxLayout) -> None:
        if self._entry.meaning_groups:
            for group in self._entry.meaning_groups:
                for sense in group.senses:
                    text = sense.gloss.strip()
                    if not text and sense.sub_senses:
                        text = sense.sub_senses[0].gloss.strip()
                    if not text:
                        continue
                    row = QtWidgets.QLabel(f"{sense.number or ''}. {text}".strip())
                    row.setObjectName("entryDetailSenseRow")
                    row.setTextFormat(QtCore.Qt.PlainText)
                    row.setWordWrap(True)
                    layout.addWidget(row)
            return

        # Fallback: no nested meaning_groups (entry came from Excel-only
        # row). Split the summary string into individual sense rows so
        # multi-sense words read top-to-bottom instead of as one wall.
        for index, gloss in enumerate(_split_summary_senses(self._entry.meanings_summary), start=1):
            row = QtWidgets.QLabel(f"{index}. {gloss}")
            row.setObjectName("entryDetailSenseRow")
            row.setTextFormat(QtCore.Qt.PlainText)
            row.setWordWrap(True)
            layout.addWidget(row)

    def _add_examples(self, layout: QtWidgets.QVBoxLayout) -> None:
        examples = self._entry.examples_flat or collect_examples_flat(self._entry)
        if not examples:
            return
        label = QtWidgets.QLabel("예문")
        label.setObjectName("entryDetailSection")
        layout.addWidget(label)
        for ex in examples:
            text = ex.source_text_plain or ex.source_text
            if ex.translation_ko:
                text += f"\n{ex.translation_ko}"
            row = _TtsTextLabel(text, ex.source_text_plain or ex.source_text)
            row.setObjectName("entryDetailExampleRow")
            row.clicked.connect(self._request_tts_for_text)
            row.setTextFormat(QtCore.Qt.PlainText)
            row.setWordWrap(True)
            layout.addWidget(row)

    def _add_word_list(self, layout: QtWidgets.QVBoxLayout, title: str, words: list[str]) -> None:
        if not words:
            return
        label = QtWidgets.QLabel(title)
        label.setObjectName("entryDetailSection")
        layout.addWidget(label)
        visible = words[:20]
        text = ", ".join(visible)
        if len(words) > len(visible):
            text += f" · 외 {len(words) - len(visible)}개"
        row = QtWidgets.QLabel(text)
        row.setObjectName("entryDetailSenseRow")
        row.setTextFormat(QtCore.Qt.PlainText)
        row.setWordWrap(True)
        layout.addWidget(row)

    def _add_text_block(self, layout: QtWidgets.QVBoxLayout, title: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        label = QtWidgets.QLabel(title)
        label.setObjectName("entryDetailSection")
        layout.addWidget(label)
        row = QtWidgets.QLabel(text)
        row.setObjectName("entryDetailSenseRow")
        row.setTextFormat(QtCore.Qt.PlainText)
        row.setWordWrap(True)
        layout.addWidget(row)

    def _add_source(self, layout: QtWidgets.QVBoxLayout) -> None:
        url = (self._entry.source_url or "").strip()
        source = _source_label(self._entry.source_provider or "", url)
        if not url and not source:
            return
        text = f"source: {source or _display_url(url)}"
        if url:
            row = QtWidgets.QLabel(
                f'<a style="color:#817b72; text-decoration:none;" href="{escape(url)}">'
                f"{escape(text)}</a>"
            )
            row.setOpenExternalLinks(True)
            row.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        else:
            row = QtWidgets.QLabel(text)
            row.setTextFormat(QtCore.Qt.PlainText)
        row.setObjectName("entryDetailSourceMeta")
        row.setWordWrap(True)
        layout.addWidget(row)


def _source_label(provider: str, url: str) -> str:
    if provider in {"naver_en", "naver_ja", "naver_api"}:
        return "NAVER"
    if provider == "manual":
        return "Manual"
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if "naver." in domain:
        return "NAVER"
    return domain.removeprefix("www.")


def _display_url(url: str, limit: int = 72) -> str:
    parsed = urlparse(url)
    shown = (parsed.netloc + parsed.path).strip("/") if parsed.netloc else url
    if parsed.query and len(shown) < limit:
        shown = f"{shown}?{parsed.query}"
    if len(shown) <= limit:
        return shown
    head = max(12, (limit - 1) // 2)
    tail = max(12, limit - head - 1)
    return f"{shown[:head]}…{shown[-tail:]}"


def _primary_form(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for sep in ("·", "・", "/", "\\"):
        if sep in text:
            return text.split(sep, 1)[0].strip()
    return text


def _split_summary_senses(summary: str) -> list[str]:
    """Split a meanings_summary string back into individual sense glosses.

    Input formats we tolerate:
      "[Noun] 1. apple 2. computer brand"
      "1. 비관적인"
      "[명사] 1. 월일 2. 시일 3. 달과 날"
    Returns: ["apple", "computer brand"] / ["비관적인"] / ["월일", "시일", "달과 날"].
    """
    import re

    if not summary:
        return []
    # Drop leading "[POS] " if present.
    body = re.sub(r"^\[[^\]]+\]\s*", "", summary).strip()
    if not body:
        return []
    # Split on " <digits>. " — keep the text after each number.
    parts = re.split(r"\s*\d+\s*\.\s*", body)
    cleaned = [p.strip() for p in parts if p.strip()]
    return cleaned or [body]


def _first_gloss(entry: VocabularyEntry) -> str:
    for group in entry.meaning_groups:
        for sense in group.senses:
            if sense.gloss:
                return sense.gloss.strip()
            for sub in sense.sub_senses:
                if sub.gloss:
                    return sub.gloss.strip()
    summary = entry.meanings_summary or build_meanings_summary(entry)
    if not summary:
        return ""
    senses = _split_summary_senses(summary)
    if senses:
        # Show only the first sense in the header; the body section
        # below renders every sense on its own row for multi-meaning
        # entries so the user can scan them line-by-line.
        return senses[0]
    return summary


def _dot_icon(*, enabled: bool) -> QtGui.QIcon:
    size = 12
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setBrush(QtGui.QColor("#e8744f" if enabled else "#6a6963"))
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawEllipse(QtCore.QRectF(2, 2, 8, 8))
    painter.end()
    return QtGui.QIcon(pixmap)


class _TtsTextLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal(str)

    def __init__(self, text: str, tts_text: str) -> None:
        super().__init__(text)
        self._tts_text = tts_text
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self._tts_text)
            event.accept()
            return
        super().mousePressEvent(event)


class _DetailToast(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("entryDetailTtsToast")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.message_label = QtWidgets.QLabel("")
        self.message_label.setObjectName("entryDetailTtsToastMessage")
        self.message_label.setTextFormat(QtCore.Qt.PlainText)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self.message_label)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade.finished.connect(self._finish_fade)
        parent.installEventFilter(self)
        self.hide()

    def show_message(self, message: str) -> None:
        message = (message or "").strip()
        if not message:
            return
        self._timer.stop()
        self._fade.stop()
        self.message_label.setText(message)
        self.adjustSize()
        self._place()
        self._opacity.setOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(2600)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.parent() and event.type() == QtCore.QEvent.Resize:
            self._place()
        return super().eventFilter(watched, event)

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        hint = self.sizeHint()
        width = min(max(hint.width(), 220), max(220, parent.width() - 56))
        height = max(hint.height(), 34)
        self.resize(width, height)
        self.move((parent.width() - width) // 2, max(18, parent.height() - height - 26))

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _finish_fade(self) -> None:
        if self._opacity.opacity() <= 0.01:
            self.hide()


class _DetailTtsWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str, object)

    def __init__(self, text: str, language: str, settings: Settings) -> None:
        super().__init__()
        self._text = text
        self._language = language
        self._settings = settings

    @QtCore.Slot()
    def run(self) -> None:
        try:
            path = synthesize_text_audio_in_process(
                self._text,
                self._language,
                self._settings,
            )
        except Exception as exc:
            self.finished.emit(False, f"TTS 생성 실패: {exc}", None)
            return
        if path is None:
            self.finished.emit(False, "TTS가 없는 단어입니다.", None)
            return
        self.finished.emit(True, "", path)
