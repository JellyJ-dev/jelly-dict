from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.core.models import VocabularyEntry
from app.storage.settings_store import Settings
from app.tts.audio_service import cached_audio_path_for_text
from app.ui.dialog_shortcuts import install_standard_close_shortcut
from app.ui.entry_detail_renderer import (
    EntryDetailSectionRenderer,
    _TtsTextLabel,
)
from app.ui.entry_detail_tts import DetailTtsPlaybackController
from app.ui.entry_detail_view_model import EntryDetailViewModel


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
        self._view_model = EntryDetailViewModel.from_entry(entry)
        self._settings = settings
        self.setObjectName("entryDetailDialog")
        self.setWindowTitle(self._view_model.title or "단어 상세")
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
        self.tts_button = QtWidgets.QPushButton("TTS")
        self.tts_button.setObjectName("entryDetailTtsButton")
        self.tts_button.setCheckable(True)
        self._tts_controller = DetailTtsPlaybackController(
            self,
            self.tts_button,
            language=self._entry.language,
            settings=self._settings,
        )
        self.tts_button.setChecked(self._tts_controller.click_enabled)
        self.tts_button.setIconSize(QtCore.QSize(9, 9))
        self.tts_button.clicked.connect(self._on_tts_toggle)
        self._sync_tts_button_state()
        header.addWidget(self.tts_button)
        header.addSpacing(8)
        close_btn = QtWidgets.QPushButton("×")
        close_btn.setObjectName("entryDetailClose")
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)

        title = _TtsTextLabel(self._view_model.title, self._view_model.title)
        title.setObjectName("entryDetailTitle")
        title.clicked.connect(self._request_tts_for_text)
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setTextFormat(QtCore.Qt.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)

        if self._view_model.full_form:
            full_label = _TtsTextLabel(
                self._view_model.full_form,
                self._view_model.full_form,
            )
            full_label.setObjectName("entryDetailMeta")
            full_label.clicked.connect(self._request_tts_for_text)
            full_label.setAlignment(QtCore.Qt.AlignCenter)
            full_label.setTextFormat(QtCore.Qt.PlainText)
            full_label.setWordWrap(True)
            layout.addWidget(full_label)

        if self._view_model.reading:
            reading_label = QtWidgets.QLabel(f"[{self._view_model.reading.strip('[] ')}]")
            reading_label.setObjectName("entryDetailReading")
            reading_label.setAlignment(QtCore.Qt.AlignCenter)
            reading_label.setTextFormat(QtCore.Qt.PlainText)
            reading_label.setWordWrap(True)
            layout.addWidget(reading_label)

        if self._view_model.first_gloss:
            summary_label = QtWidgets.QLabel(self._view_model.first_gloss)
            summary_label.setObjectName("entryDetailSummary")
            summary_label.setAlignment(QtCore.Qt.AlignCenter)
            summary_label.setTextFormat(QtCore.Qt.PlainText)
            summary_label.setWordWrap(True)
            layout.addWidget(summary_label)

        if self._view_model.meta:
            meta_label = QtWidgets.QLabel(self._view_model.meta)
            meta_label.setObjectName("entryDetailMeta")
            meta_label.setAlignment(QtCore.Qt.AlignCenter)
            meta_label.setTextFormat(QtCore.Qt.PlainText)
            layout.addWidget(meta_label)

        divider_top = QtWidgets.QFrame()
        divider_top.setObjectName("entryDetailDivider")
        divider_top.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(divider_top)

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

        self._section_renderer = EntryDetailSectionRenderer(
            self._view_model,
            self._request_tts_for_text,
        )
        self._section_renderer.render(body_layout)
        body_layout.addStretch(1)
        self._tts_toast = _DetailToast(self)
        self._tts_controller.set_toast(self._tts_toast)

    def _is_tts_running(self) -> bool:
        return self._tts_controller.is_running()

    def _ready_for_close(self) -> bool:
        return self._tts_controller.ready_for_close()

    def done(self, result: int) -> None:
        if not self._ready_for_close():
            return
        super().done(result)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self._ready_for_close():
            event.ignore()
            return
        super().closeEvent(event)

    def _sync_tts_button_state(self) -> None:
        self._tts_controller.sync_button_state()

    def _on_tts_toggle(self, checked: bool) -> None:
        self._tts_controller.toggle(checked)

    @QtCore.Slot(str)
    def _request_tts_for_text(self, text: str) -> None:
        self._tts_controller.request(text)

    def _lookup_cached_tts(self, text: str) -> Path | None:
        if self._settings is None:
            return None
        return cached_audio_path_for_text(text, self._entry.language, self._settings)

    def _on_tts_finished(self, ok: bool, message: str, path_obj: object) -> None:
        self._tts_controller.on_finished(ok, message, path_obj)

    def _clear_tts_worker(self) -> None:
        self._tts_controller.clear_worker()

    def _play_audio_file(self, path: Path) -> None:
        self._tts_controller.play_audio_file(path)

    def _show_tts_message(self, message: str) -> None:
        self._tts_controller.show_message(message)

    @property
    def _tts_thread(self):
        return self._tts_controller.thread

    @_tts_thread.setter
    def _tts_thread(self, value) -> None:
        self._tts_controller.thread = value

    @property
    def _tts_worker(self):
        return self._tts_controller.worker

    @property
    def _tts_click_enabled(self) -> bool:
        return self._tts_controller.click_enabled

    @property
    def _tts_player(self):
        return self._tts_controller.player


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
