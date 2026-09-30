"""TTS (text-to-speech) provider layer for Anki audio.

The provider registry is the single entry point. Each provider declares its
own ``is_available()`` so the app can boot even when optional engines are
missing. License/usage metadata is mandatory and gets surfaced to the user
through the settings UI and the deck description.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.anki.tts.base import (
    NoTTSProvider,
    ProviderInfo,
    TTSProvider,
    TTSResult,
)

if TYPE_CHECKING:
    from app.storage.settings_store import Settings


def list_provider_classes() -> dict[str, type[TTSProvider]]:
    from app.providers import get_provider_registry

    classes: dict[str, type[TTSProvider]] = {}
    for descriptor in get_provider_registry().descriptors("tts"):
        implementation = descriptor.implementation_class()
        if implementation is not None:
            classes[descriptor.id] = implementation
    return classes


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


def build_provider(
    name: str,
    settings: "Settings",
    language: str | None = None,
) -> TTSProvider:
    """Construct a provider instance, or NoTTSProvider when disabled/missing."""
    if not name or name == "none":
        return NoTTSProvider()
    from app.providers import get_provider_registry

    try:
        registry = get_provider_registry()
        if language is not None:
            capability = registry.capabilities("tts", name, settings)
            voice = getattr(
                settings,
                "tts_voice_ja" if language == "ja" else "tts_voice_en",
                "",
            )
            if capability.availability_for(language) == "missing":
                return NoTTSProvider()
            if voice and capability.availability_for_voice(language, voice) == "missing":
                return NoTTSProvider()
        provider = registry.create("tts", name, settings)
    except ValueError:
        # Compatibility seam for tests/plugins that still monkeypatch the
        # former class mapping. Registered providers always use the registry.
        provider_class = list_provider_classes().get(name)
        if provider_class is None or not provider_class.is_available():
            return NoTTSProvider()
        return provider_class(settings)
    return provider  # type: ignore[return-value]


__all__ = [
    "TTSProvider",
    "TTSResult",
    "ProviderInfo",
    "NoTTSProvider",
    "list_provider_classes",
    "get_provider_info",
    "build_provider",
]
