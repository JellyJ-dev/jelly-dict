from __future__ import annotations

from pathlib import Path

from app.ocr.base import OcrResult, OcrToken, normalize_ocr_tokens
from app.ocr.image_input import normalized_ocr_image_path


class AppleVisionOcrProvider:
    """Local macOS Vision OCR provider.

    PyObjC imports stay inside extract() so non-macOS test runs and plain
    imports do not require the Vision framework to be present.
    """

    def extract(self, image_path: Path) -> OcrResult:
        path = Path(image_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))

        try:
            from Foundation import NSURL
            from Vision import (
                VNImageRequestHandler,
                VNRecognizeTextRequest,
                VNRequestTextRecognitionLevelAccurate,
            )
        except Exception as exc:  # pragma: no cover - depends on local macOS deps
            raise RuntimeError(
                "Apple Vision OCR 의존성이 없습니다. requirements.txt를 설치하세요."
            ) from exc

        request = VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(VNRequestTextRecognitionLevelAccurate)
        if hasattr(request, "setUsesLanguageCorrection_"):
            request.setUsesLanguageCorrection_(True)
        if hasattr(request, "setRecognitionLanguages_"):
            request.setRecognitionLanguages_(["en-US", "ja-JP", "ko-KR"])

        with normalized_ocr_image_path(path) as normalized_path:
            url = NSURL.fileURLWithPath_(str(normalized_path))
            handler = VNImageRequestHandler.alloc().initWithURL_options_(url, {})
            try:
                performed = handler.performRequests_error_([request], None)
            except Exception as exc:  # pragma: no cover - Vision runtime specific
                raise RuntimeError(f"Apple Vision OCR 실행 실패: {exc}") from exc

        if isinstance(performed, tuple):
            ok, error = performed
            if not ok:
                raise RuntimeError(f"Apple Vision OCR 실패: {error}")

        observations = request.results() or []
        raw_tokens: list[OcrToken] = []
        for observation in observations:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            raw_tokens.append(OcrToken(str(candidate.string()), float(candidate.confidence())))
        return OcrResult(normalize_ocr_tokens(raw_tokens))
