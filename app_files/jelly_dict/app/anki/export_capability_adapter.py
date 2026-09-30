from __future__ import annotations

import importlib.util

from app.anki.tts import get_provider_info
from app.anki.tts.voicevox_provider import VoicevoxProvider
from app.providers import get_provider_registry


class AnkiExportCapabilities:
    def genanki_available(self) -> bool:
        return importlib.util.find_spec("genanki") is not None

    def tts_provider_info(self, engine: str):
        return get_provider_info(engine)

    def tts_provider_capabilities(self, engine: str):
        return get_provider_registry().capabilities("tts", engine)

    def voicevox_running(self, url: str, timeout: float) -> bool:
        return VoicevoxProvider.is_running(url, timeout=timeout)
