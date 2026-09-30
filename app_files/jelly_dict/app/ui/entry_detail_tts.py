"""TTS playback lifecycle for the entry-detail dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.storage.settings_store import Settings
from app.tts.audio_service import tts_configured
from app.tts.process_service import synthesize_text_audio_in_process


class DetailTtsPlaybackController:
    def __init__(
        self,
        dialog: QtWidgets.QDialog,
        button: QtWidgets.QPushButton,
        *,
        language: str,
        settings: Settings | None,
    ) -> None:
        self.dialog = dialog
        self.button = button
        self.language = language
        self.settings = settings
        self.toast = None
        self.thread: QtCore.QThread | None = None
        self.worker: _DetailTtsWorker | None = None
        self.click_enabled = tts_configured(settings, language)
        self.player = None

    def set_toast(self, toast: object) -> None:
        self.toast = toast

    def sync_button_state(self) -> None:
        configured = tts_configured(self.settings, self.language)
        if not configured:
            self.click_enabled = False
            self.button.setChecked(False)
        else:
            self.click_enabled = self.button.isChecked()
        self.button.setEnabled(True)
        self.button.setIcon(_dot_icon(enabled=configured and self.click_enabled))
        self.button.setToolTip(
            "단어/예문 클릭 재생 활성"
            if configured and self.click_enabled
            else "단어/예문 클릭 재생 비활성"
        )

    def toggle(self, checked: bool) -> None:
        if not tts_configured(self.settings, self.language):
            self.click_enabled = False
            self.button.setChecked(False)
            self.sync_button_state()
            self.show_message("TTS가 없는 단어입니다.")
            return
        self.click_enabled = checked
        self.sync_button_state()

    def is_running(self) -> bool:
        if self.thread is None:
            return False
        try:
            return self.thread.isRunning()
        except RuntimeError:
            self.clear_worker()
            return False

    def ready_for_close(self) -> bool:
        if self.is_running():
            self.show_message("TTS 생성이 끝난 뒤 닫을 수 있습니다.")
            return False
        return True

    def request(self, text: str) -> None:
        text = (text or "").strip()
        if not self.click_enabled:
            return
        if self.settings is None or self.thread is not None:
            if self.thread is not None:
                self.show_message("TTS 생성 중입니다.")
            return
        if not tts_configured(self.settings, self.language):
            self.sync_button_state()
            self.show_message("TTS가 없는 단어입니다.")
            return
        if not text:
            self.show_message("TTS가 없는 단어입니다.")
            return
        cached = self.dialog._lookup_cached_tts(text)  # type: ignore[attr-defined]
        if cached is not None:
            self.dialog._play_audio_file(cached)  # type: ignore[attr-defined]
            return

        self.thread = QtCore.QThread(self.dialog)
        self.worker = _DetailTtsWorker(text, self.language, self.settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.clear_worker)
        self.thread.start()

    @QtCore.Slot(bool, str, object)
    def on_finished(self, ok: bool, message: str, path_obj: object) -> None:
        self.sync_button_state()
        if ok and isinstance(path_obj, Path):
            self.dialog._play_audio_file(path_obj)  # type: ignore[attr-defined]
            return
        self.show_message(message or "TTS가 없는 단어입니다.")

    @QtCore.Slot()
    def clear_worker(self) -> None:
        self.thread = None
        self.worker = None

    def play_audio_file(self, path: Path) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            self.button.setToolTip("QtMultimedia를 사용할 수 없습니다.")
            return
        player = QMediaPlayer(self.dialog)
        audio_output = QAudioOutput(self.dialog)
        player.setAudioOutput(audio_output)
        player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        player.play()
        self.player = (player, audio_output)

    def show_message(self, message: str) -> None:
        if self.toast is not None:
            self.toast.show_message(message)  # type: ignore[attr-defined]


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


__all__ = ["DetailTtsPlaybackController"]
