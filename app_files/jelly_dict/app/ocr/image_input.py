from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, cast

from PySide6 import QtCore, QtGui

from app.core import config

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_PIXELS = 50_000_000
MAX_DECODED_DIMENSION = 3_072
MAX_ENCODED_BYTES = 10 * 1024 * 1024


class OcrImageInputError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedOcrImage:
    data: bytes
    width: int
    height: int


def prepare_ocr_image(path: Path) -> PreparedOcrImage:
    source = Path(path).expanduser()
    try:
        size_bytes = source.stat().st_size
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise OcrImageInputError(f"OCR 이미지 정보를 읽을 수 없습니다: {exc}") from exc
    if size_bytes > MAX_SOURCE_BYTES:
        raise OcrImageInputError("OCR 이미지 파일이 너무 큽니다.")

    reader = QtGui.QImageReader(str(source))
    reader.setAutoTransform(True)
    source_size = reader.size()
    if not source_size.isValid() or source_size.isEmpty():
        raise OcrImageInputError("지원하지 않거나 손상된 이미지입니다.")
    source_pixels = source_size.width() * source_size.height()
    if source_pixels > MAX_SOURCE_PIXELS:
        raise OcrImageInputError("OCR 이미지 해상도가 너무 큽니다.")

    if source_size.width() > MAX_DECODED_DIMENSION or source_size.height() > MAX_DECODED_DIMENSION:
        scaled_size = source_size.scaled(
            MAX_DECODED_DIMENSION,
            MAX_DECODED_DIMENSION,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        )
        reader.setScaledSize(scaled_size)
    image = reader.read()
    if image.isNull():
        message = reader.errorString() or "이미지 디코딩 실패"
        raise OcrImageInputError(f"OCR 이미지를 읽을 수 없습니다: {message}")
    if image.width() > MAX_DECODED_DIMENSION or image.height() > MAX_DECODED_DIMENSION:
        image = image.scaled(
            MAX_DECODED_DIMENSION,
            MAX_DECODED_DIMENSION,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )

    normalized = QtGui.QImage(image.size(), QtGui.QImage.Format.Format_RGB32)
    normalized.fill(QtCore.Qt.GlobalColor.white)
    painter = QtGui.QPainter(normalized)
    try:
        painter.drawImage(0, 0, image)
    finally:
        painter.end()

    encoded = _encode_jpeg(normalized, quality=90)
    if len(encoded) > MAX_ENCODED_BYTES:
        encoded = _encode_jpeg(normalized, quality=70)
    if len(encoded) > MAX_ENCODED_BYTES:
        raise OcrImageInputError("OCR 변환 이미지가 너무 큽니다.")
    return PreparedOcrImage(encoded, normalized.width(), normalized.height())


@contextmanager
def normalized_ocr_image_path(path: Path) -> Iterator[Path]:
    prepared = prepare_ocr_image(path)
    directory = config.runtime_dir() / "ocr_normalized"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=directory,
            prefix="ocr-",
            suffix=".jpg",
        ) as temp_file:
            temp_name = temp_file.name
            os.chmod(temp_name, 0o600)
            temp_file.write(prepared.data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        yield Path(temp_name)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _encode_jpeg(image: QtGui.QImage, *, quality: int) -> bytes:
    buffer = QtCore.QBuffer()
    if not buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        raise OcrImageInputError("OCR 이미지 버퍼를 만들 수 없습니다.")
    try:
        writer = QtGui.QImageWriter(buffer, b"JPEG")
        writer.setQuality(quality)
        if not writer.write(image):
            raise OcrImageInputError("OCR 이미지를 변환할 수 없습니다.")
        return cast(bytes, buffer.data().data())
    finally:
        buffer.close()
