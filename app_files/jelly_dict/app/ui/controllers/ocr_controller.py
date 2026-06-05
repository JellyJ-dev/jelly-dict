from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from app.ocr import OcrProvider
from app.ocr import temp_files as ocr_temp_files
from app.ui.ocr_worker import OcrWorker
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class OcrController(QtCore.QObject):
    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget,
        input_view: WordInputView,
        status_bar,
        provider: OcrProvider,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._input_view = input_view
        self._status = status_bar
        self._provider = provider
        self._thread: QtCore.QThread | None = None
        self._worker: OcrWorker | None = None
        self._temp_path: Path | None = None

    def update_provider(self, provider: OcrProvider) -> None:
        self._provider = provider

    def cleanup_temp_dir_idle(self) -> None:
        ocr_temp_files.cleanup_temp_dir()

    def open_image(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._parent,
            "사진 선택",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.heic)",
        )
        if path:
            self.start_for_path(path)

    @QtCore.Slot(str)
    def start_for_path(self, path_text: str, temp_path: Path | None = None) -> None:
        if self.is_running():
            self._status.showMessage("이미 사진 텍스트 인식 중입니다.")
            if temp_path is not None:
                ocr_temp_files.remove_temp_file(temp_path)
            return

        image_path = Path(path_text).expanduser()
        self.cleanup_current_temp()
        self._temp_path = temp_path
        self._input_view.show_ocr_image(str(image_path))
        self._status.showMessage("사진 텍스트 인식 중...")

        thread = QtCore.QThread(self)
        worker = OcrWorker(self._provider, image_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_worker_refs)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    @QtCore.Slot(object)
    def start_for_clipboard_image(self, image_obj: object) -> None:
        if self.is_running():
            self._status.showMessage("이미 사진 텍스트 인식 중입니다.")
            return
        if not isinstance(image_obj, QtGui.QImage) or image_obj.isNull():
            self._status.showMessage("붙여넣은 이미지가 비어 있습니다.")
            return
        image_dir = ocr_temp_files.temp_dir()
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"paste-{uuid4().hex}.png"
        if not image_obj.save(str(image_path), "PNG"):
            log.warning("clipboard image save failed: %s", image_path)
            self._status.showMessage("붙여넣은 이미지 저장 실패")
            return
        self.start_for_path(str(image_path), temp_path=image_path)

    def is_running(self) -> bool:
        if self._thread is None:
            return False
        try:
            return self._thread.isRunning()
        except RuntimeError:
            self._clear_worker_refs()
            return False

    def close(self) -> None:
        try:
            if self._thread is not None and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)
        except Exception as exc:
            log.warning("ocr thread cleanup failed: %s", exc)

    def _clear_worker_refs(self) -> None:
        self._thread = None
        self._worker = None

    @QtCore.Slot()
    def cleanup_current_temp(self) -> None:
        ocr_temp_files.remove_temp_file(self._temp_path)
        self._temp_path = None

    @QtCore.Slot(object)
    def _on_finished(self, result) -> None:
        tokens = [token.text for token in getattr(result, "tokens", [])]
        self._input_view.set_ocr_tokens(tokens)
        self._status.showMessage(f"OCR 후보 {len(tokens)}개")

    @QtCore.Slot(str)
    def _on_failed(self, message: str) -> None:
        log.warning("ocr failed: %s", message)
        self._input_view.set_ocr_error("인식 실패")
        self._status.showMessage("사진 텍스트 인식 실패")
