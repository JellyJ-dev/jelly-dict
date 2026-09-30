from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

ProviderKind = Literal["dictionary", "ocr", "tts"]
ProviderLocality = Literal["local", "remote", "local_service"]
DependencyStatus = Literal["available", "missing", "unknown"]


@dataclass(frozen=True)
class VoiceCapability:
    id: str
    language: str


@dataclass(frozen=True)
class DependencyCapability:
    id: str
    status: DependencyStatus
    languages: tuple[str, ...] = ()
    voices: tuple[str, ...] = ()
    detail: str = ""

    def applies_to(self, language: str, voice: str | None = None) -> bool:
        if self.languages and language not in self.languages:
            return False
        if self.voices:
            return voice is not None and voice in self.voices
        return True


@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    kind: ProviderKind
    display_name: str
    languages: tuple[str, ...]
    locality: ProviderLocality
    dependencies: tuple[DependencyCapability, ...] = ()
    voices: tuple[VoiceCapability, ...] = ()

    def supports(self, language: str) -> bool:
        return language in self.languages

    def voices_for(self, language: str) -> tuple[str, ...]:
        return tuple(voice.id for voice in self.voices if voice.language == language)

    def availability_for(self, language: str) -> DependencyStatus:
        if not self.supports(language):
            return "missing"
        relevant = tuple(
            dependency for dependency in self.dependencies if dependency.applies_to(language)
        )
        if any(dependency.status == "missing" for dependency in relevant):
            return "missing"
        if any(dependency.status == "unknown" for dependency in relevant):
            return "unknown"
        return "available"

    def availability_for_voice(
        self,
        language: str,
        voice: str,
    ) -> DependencyStatus:
        if voice not in self.voices_for(language):
            return "missing"
        relevant = tuple(
            dependency for dependency in self.dependencies if dependency.applies_to(language, voice)
        )
        if any(dependency.status == "missing" for dependency in relevant):
            return "missing"
        if any(dependency.status == "unknown" for dependency in relevant):
            return "unknown"
        return "available"


CapabilityLoader = Callable[[Any | None], ProviderCapability]
Factory = Callable[[Any], object]
ClassLoader = Callable[[], type]


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    kind: ProviderKind
    display_name: str
    visible_in_settings: bool
    capability_loader: CapabilityLoader
    factory: Factory
    class_loader: ClassLoader | None = None
    short_label: str = ""
    subtitle_available: str = ""
    subtitle_missing: str = ""
    status_label: str = ""
    selection_requires_dependencies: bool = False

    def capabilities(self, settings: Any | None = None) -> ProviderCapability:
        return self.capability_loader(settings)

    def create(self, settings: Any) -> object:
        return self.factory(settings)

    def implementation_class(self) -> type | None:
        return self.class_loader() if self.class_loader is not None else None


class ProviderRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[tuple[ProviderKind, str], ProviderDescriptor] = {}

    def register(self, descriptor: ProviderDescriptor) -> None:
        key = (descriptor.kind, descriptor.id)
        if key in self._descriptors:
            raise ValueError(f"provider already registered: {descriptor.kind}/{descriptor.id}")
        self._descriptors[key] = descriptor

    def descriptor(self, kind: ProviderKind, provider_id: str) -> ProviderDescriptor:
        try:
            return self._descriptors[(kind, provider_id)]
        except KeyError as exc:
            raise ValueError(f"unsupported {kind} provider: {provider_id}") from exc

    def descriptors(
        self,
        kind: ProviderKind,
        *,
        settings_only: bool = False,
    ) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor in self._descriptors.values()
            if descriptor.kind == kind and (descriptor.visible_in_settings or not settings_only)
        )

    def capabilities(
        self,
        kind: ProviderKind,
        provider_id: str,
        settings: Any | None = None,
    ) -> ProviderCapability:
        return self.descriptor(kind, provider_id).capabilities(settings)

    def create(self, kind: ProviderKind, provider_id: str, settings: Any) -> object:
        return self.descriptor(kind, provider_id).create(settings)


_REGISTRY: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        registry = ProviderRegistry()
        _register_dictionary(registry)
        _register_ocr(registry)
        _register_tts(registry)
        _REGISTRY = registry
    return _REGISTRY


def _register_dictionary(registry: ProviderRegistry) -> None:
    registry.register(
        ProviderDescriptor(
            id="naver_crawler",
            kind="dictionary",
            display_name="네이버 사전",
            visible_in_settings=True,
            capability_loader=lambda _settings: ProviderCapability(
                "naver_crawler",
                "dictionary",
                "네이버 사전",
                ("en", "ja"),
                "remote",
                dependencies=(DependencyCapability("playwright-browser", "available"),),
            ),
            factory=_create_naver_dictionary,
            class_loader=_naver_class,
            status_label="Naver",
        )
    )
    registry.register(
        ProviderDescriptor(
            id="manual",
            kind="dictionary",
            display_name="직접 입력",
            visible_in_settings=False,
            capability_loader=lambda _settings: ProviderCapability(
                "manual",
                "dictionary",
                "직접 입력",
                ("en", "ja"),
                "local",
            ),
            factory=lambda _settings: _manual_class()(),
            class_loader=_manual_class,
            status_label="Manual",
        )
    )


def _register_ocr(registry: ProviderRegistry) -> None:
    registry.register(
        ProviderDescriptor(
            id="apple_vision",
            kind="ocr",
            display_name="Apple Vision (로컬)",
            visible_in_settings=True,
            capability_loader=_apple_vision_capabilities,
            factory=lambda _settings: _apple_vision_class()(),
            class_loader=_apple_vision_class,
            short_label="Apple Vision",
            subtitle_available="macOS 로컬 OCR",
            subtitle_missing="macOS 로컬 OCR",
        )
    )
    registry.register(
        ProviderDescriptor(
            id="google_vision",
            kind="ocr",
            display_name="Google Cloud Vision (사용자 API 키)",
            visible_in_settings=True,
            capability_loader=_google_vision_capabilities,
            factory=_create_google_vision,
            class_loader=_google_vision_class,
            short_label="Google Vision",
            subtitle_available="사용자 API 키",
            subtitle_missing="API 키 입력 후 사용 가능",
            selection_requires_dependencies=True,
        )
    )


def _register_tts(registry: ProviderRegistry) -> None:
    for provider_id, display_name, locality, class_loader in (
        ("kokoro", "Kokoro (로컬)", "local", _kokoro_class),
        ("voicevox", "VOICEVOX (로컬 엔진)", "local_service", _voicevox_class),
        ("edge", "edge-tts (외부 CLI)", "remote", _edge_class),
    ):
        registry.register(
            ProviderDescriptor(
                id=provider_id,
                kind="tts",
                display_name=display_name,
                visible_in_settings=True,
                capability_loader=_tts_capability_loader(
                    provider_id,
                    display_name,
                    locality,  # type: ignore[arg-type]
                    class_loader,
                ),
                factory=_tts_factory(provider_id, class_loader),
                class_loader=class_loader,
            )
        )


def _tts_capability_loader(
    provider_id: str,
    display_name: str,
    locality: ProviderLocality,
    class_loader: ClassLoader,
) -> CapabilityLoader:
    def load(_settings: Any | None) -> ProviderCapability:
        info = class_loader().info()
        voices = tuple(
            VoiceCapability(voice, language)
            for language, values in (("en", info.voices_en), ("ja", info.voices_ja))
            for voice in values
        )
        languages = tuple(
            language
            for language, values in (("en", info.voices_en), ("ja", info.voices_ja))
            if values
        )
        dependency_id = {
            "kokoro": "kokoro-runtime-model",
            "voicevox": "voicevox-local-engine",
            "edge": "edge-tts-cli",
        }[provider_id]
        provider_class = class_loader()
        runtime_available_for = getattr(
            provider_class,
            "runtime_available_for",
            None,
        )
        voice_available = getattr(provider_class, "is_voice_available", None)
        if callable(runtime_available_for):
            runtime_dependencies = tuple(
                DependencyCapability(
                    dependency_id,
                    "available" if runtime_available_for(language) else "missing",
                    languages=(language,),
                )
                for language in languages
            )
            voice_dependencies = (
                tuple(
                    DependencyCapability(
                        f"{dependency_id}-voice:{voice.id}",
                        ("available" if voice_available(voice.id, voice.language) else "missing"),
                        languages=(voice.language,),
                        voices=(voice.id,),
                    )
                    for voice in voices
                )
                if callable(voice_available)
                else ()
            )
            dependencies = (*runtime_dependencies, *voice_dependencies)
        else:
            status: DependencyStatus = (
                "unknown"
                if provider_id == "voicevox"
                else ("available" if info.available else "missing")
            )
            dependencies = (DependencyCapability(dependency_id, status),)
        return ProviderCapability(
            provider_id,
            "tts",
            display_name,
            languages,
            locality,
            dependencies=dependencies,
            voices=voices,
        )

    return load


def _tts_factory(provider_id: str, class_loader: ClassLoader) -> Factory:
    def create(settings: Any) -> object:
        provider_class = class_loader()
        if not provider_class.is_available():
            from app.anki.tts.base import NoTTSProvider

            return NoTTSProvider()
        return provider_class(settings)

    return create


def _create_naver_dictionary(settings: Any) -> object:
    provider = _naver_class()()
    provider.client.update_delay(settings.request_delay_seconds)
    return provider


def _create_google_vision(settings: Any) -> object:
    from app.storage import secret_store

    key = secret_store.get("google_vision_api_key")
    if not key:
        raise RuntimeError("Google Vision OCR을 사용하려면 설정에서 API 키를 입력하세요.")
    return _google_vision_class()(key, settings.google_vision_endpoint)


def _apple_vision_capabilities(_settings: Any | None) -> ProviderCapability:
    available = (
        importlib.util.find_spec("Foundation") is not None
        and importlib.util.find_spec("Vision") is not None
    )
    return ProviderCapability(
        "apple_vision",
        "ocr",
        "Apple Vision (로컬)",
        ("en", "ja"),
        "local",
        dependencies=(
            DependencyCapability(
                "pyobjc-vision",
                "available" if available else "missing",
            ),
        ),
    )


def _google_vision_capabilities(_settings: Any | None) -> ProviderCapability:
    from app.storage import secret_store

    return ProviderCapability(
        "google_vision",
        "ocr",
        "Google Cloud Vision (사용자 API 키)",
        ("en", "ja"),
        "remote",
        dependencies=(
            DependencyCapability(
                "google-vision-api-key",
                "available" if secret_store.is_set("google_vision_api_key") else "missing",
            ),
        ),
    )


def _manual_class() -> type:
    from app.dictionary.manual_provider import ManualDictionaryProvider

    return ManualDictionaryProvider


def _naver_class() -> type:
    from app.dictionary.naver_crawler import NaverDictionaryCrawlerProvider

    return NaverDictionaryCrawlerProvider


def _apple_vision_class() -> type:
    from app.ocr.apple_vision import AppleVisionOcrProvider

    return AppleVisionOcrProvider


def _google_vision_class() -> type:
    from app.ocr.google_vision import GoogleVisionOcrProvider

    return GoogleVisionOcrProvider


def _kokoro_class() -> type:
    from app.anki.tts.kokoro_provider import KokoroProvider

    return KokoroProvider


def _voicevox_class() -> type:
    from app.anki.tts.voicevox_provider import VoicevoxProvider

    return VoicevoxProvider


def _edge_class() -> type:
    from app.anki.tts.edge_provider import EdgeProvider

    return EdgeProvider
