from __future__ import annotations

from app.ocr.base import OcrProvider
from app.providers import get_provider_registry


def build_ocr_provider(name: str | None, settings=None) -> OcrProvider:
    provider = (name or "apple_vision").strip().lower()
    if settings is None:
        from app.core.settings import Settings

        settings = Settings()
    return get_provider_registry().create("ocr", provider, settings)  # type: ignore[return-value]
