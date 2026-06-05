"""TTS (text-to-speech) provider layer for Anki audio.

The provider registry is the single entry point. Each provider declares its
own ``is_available()`` so the app can boot even when optional engines are
missing. License/usage metadata is mandatory and gets surfaced to the user
through the settings UI and the deck description.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.anki.tts.base import (
    TTSProvider,
    TTSResult,
    ProviderInfo,
    NoTTSProvider,
)

if TYPE_CHECKING:
    from app.storage.settings_store import Settings


def list_provider_classes() -> dict[str, type[TTSProvider]]:
    # Lazy imports — keep module import cheap and avoid loading heavy
    # optional deps (kokoro, soundfile, ...) until actually needed.
    from app.anki.tts.kokoro_provider import KokoroProvider
    from app.anki.tts.voicevox_provider import VoicevoxProvider
    from app.anki.tts.edge_provider import EdgeProvider

    return {
        "kokoro": KokoroProvider,
        "voicevox": VoicevoxProvider,
        "edge": EdgeProvider,
    }


def get_provider_info(name: str) -> ProviderInfo:
    cls = list_provider_classes().get(name)
    if cls is None:
        return ProviderInfo(
            id="none",
            display_name="사용 안 함",
            available=True,
            voices_en=(),
            voices_ja=(),
            requires_credit=False,
            license_note="",
            usage_warning="",
        )
    return cls.info()


def build_provider(name: str, settings: "Settings") -> TTSProvider:
    """Construct a provider instance, or NoTTSProvider when disabled/missing."""
    if not name or name == "none":
        return NoTTSProvider()
    cls = list_provider_classes().get(name)
    if cls is None or not cls.is_available():
        return NoTTSProvider()
    return cls(settings)


__all__ = [
    "TTSProvider",
    "TTSResult",
    "ProviderInfo",
    "NoTTSProvider",
    "list_provider_classes",
    "get_provider_info",
    "build_provider",
]
