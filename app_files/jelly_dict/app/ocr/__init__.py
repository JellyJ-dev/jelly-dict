from __future__ import annotations

import importlib
from typing import Any

from app.ocr.base import OcrProvider, OcrResult, OcrToken, normalize_ocr_tokens

__all__ = [
    "OcrProvider",
    "OcrResult",
    "OcrToken",
    "build_ocr_provider",
    "normalize_ocr_tokens",
]


def __getattr__(name: str) -> Any:
    if name != "build_ocr_provider":
        raise AttributeError(name)
    value = getattr(importlib.import_module("app.ocr.providers"), name)
    globals()[name] = value
    return value
