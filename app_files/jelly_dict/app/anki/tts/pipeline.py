"""TTS generation pipeline used by the APKG exporter and the settings UI.

Responsibilities:
- pick the right provider for a given language
- look up the cache before generating (idempotent re-export)
- swallow per-entry failures so the whole export still succeeds
- collect provider credit metadata for the deck description
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.anki.tts import build_provider, get_provider_info
from app.anki.tts.base import TTSProvider, TTSResult
from app.tts.audio_cache import (
    AudioCache,
    AudioLease,
    acquire_audio_lease,
    cache_key,
    wordbook_audio_dir,
)

if TYPE_CHECKING:
    from app.storage.settings_store import Settings

logger = logging.getLogger(__name__)


@dataclass
class TTSBatch:
    """Result of synthesising audio for one APKG export."""

    media_paths: list[Path] = field(default_factory=list)
    credits: set[str] = field(default_factory=set)
    _media_seen: set[Path] = field(default_factory=set, init=False, repr=False)
    _leases: list[AudioLease] = field(default_factory=list, init=False, repr=False)

    def add_media(self, path: Path) -> None:
        if path in self._media_seen:
            return
        self._media_seen.add(path)
        self.media_paths.append(path)
        lease = acquire_audio_lease(path)
        if lease is not None:
            self._leases.append(lease)

    def close(self) -> None:
        leases = getattr(self, "_leases", None)
        while leases:
            leases.pop().close()

    def __enter__(self) -> "TTSBatch":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - defensive fallback
        self.close()


class TTSPipeline:
    """Per-export pipeline. Caches provider instances keyed by name."""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._providers: dict[str, TTSProvider] = {}

    def _provider_for(self, language: str) -> tuple[TTSProvider, str]:
        if language == "ja":
            name = self._settings.tts_engine_ja
        else:
            name = self._settings.tts_engine_en
        key = f"{name}:{language}"
        if key not in self._providers:
            self._providers[key] = build_provider(
                name,
                self._settings,
                language,
            )
        return self._providers[key], name

    def _voice_for(self, language: str) -> str:
        return self._settings.tts_voice_ja if language == "ja" else self._settings.tts_voice_en

    def synthesize(
        self,
        text: str,
        language: str,
        batch: Optional[TTSBatch] = None,
    ) -> Optional[Path]:
        """Return the audio file path for ``text``, or None on failure."""
        if not text or not text.strip():
            return None
        if not self._settings.tts_enabled:
            return None

        provider, name = self._provider_for(language)
        if name == "none" or provider.__class__.__name__ == "NoTTSProvider":
            return None

        voice = self._voice_for(language)
        key = cache_key(
            language,
            name,
            voice,
            text,
            bitrate=getattr(self._settings, "tts_bitrate", ""),
            sample_rate=getattr(self._settings, "tts_sample_rate", None),
        )
        cache = AudioCache(wordbook_audio_dir(self._settings, language))
        generated: TTSResult | None = None

        def produce(temp_path: Path) -> Path:
            nonlocal generated
            generated = provider.synthesize(
                text,
                language=language,
                voice=voice,
                out_path=temp_path,
            )
            return generated.path

        try:
            cache_result = cache.get_or_create(key, produce)
        except Exception as exc:
            logger.warning(
                "TTS synth failed (%s/%s): %s",
                name,
                language,
                type(exc).__name__,
            )
            return None

        if cache_result.created and generated is not None:
            result = replace(generated, path=cache_result.path)
        else:
            # Use stored metadata when re-using cached audio: rebuild a
            # synthetic result from the provider's static info.
            info = get_provider_info(name)
            credit = ""
            if info.requires_credit:
                # Best-effort credit text reconstruction
                if name == "voicevox":
                    display = voice.split(":", 1)[1] if ":" in voice else voice
                    credit = f"VOICEVOX:{display}"
            result = TTSResult(
                path=cache_result.path,
                engine_id=name,
                voice=voice,
                requires_credit=info.requires_credit,
                credit_text=credit,
                license_note=info.license_note,
            )

        if batch is not None:
            batch.add_media(result.path)
            if result.requires_credit and result.credit_text:
                batch.credits.add(result.credit_text)

        return result.path
