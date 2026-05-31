"""TTS generation pipeline used by the APKG exporter and the settings UI.

Responsibilities:
- pick the right provider for a given language
- look up the cache before generating (idempotent re-export)
- swallow per-entry failures so the whole export still succeeds
- collect provider credit metadata for the deck description
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.anki.tts import build_provider, get_provider_info
from app.anki.tts.base import TTSResult
from app.anki.tts.cache import cache_path, is_valid_audio_file

logger = logging.getLogger(__name__)


@dataclass
class TTSBatch:
    """Result of synthesising audio for one APKG export."""
    media_paths: list[Path] = field(default_factory=list)
    credits: set[str] = field(default_factory=set)
    _media_seen: set[Path] = field(default_factory=set, init=False, repr=False)

    def add_media(self, path: Path) -> None:
        if path in self._media_seen:
            return
        self._media_seen.add(path)
        self.media_paths.append(path)


class TTSPipeline:
    """Per-export pipeline. Caches provider instances keyed by name."""

    def __init__(self, settings) -> None:
        self._settings = settings
        self._providers = {}  # name -> provider instance

    def _provider_for(self, language: str):
        if language == "ja":
            name = self._settings.tts_engine_ja
        else:
            name = self._settings.tts_engine_en
        if name not in self._providers:
            self._providers[name] = build_provider(name, self._settings)
        return self._providers[name], name

    def _voice_for(self, language: str) -> str:
        return (
            self._settings.tts_voice_ja
            if language == "ja"
            else self._settings.tts_voice_en
        )

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
        out_path = cache_path(
            language,
            name,
            voice,
            text,
            bitrate=getattr(self._settings, "tts_bitrate", ""),
            sample_rate=getattr(self._settings, "tts_sample_rate", None),
        )

        if not is_valid_audio_file(out_path):
            _remove_partial_audio(out_path)
            try:
                result: TTSResult = provider.synthesize(
                    text, language=language, voice=voice, out_path=out_path,
                )
            except Exception as exc:
                _remove_audio_file(out_path)
                logger.warning(
                    "TTS synth failed (%s/%s): %s", name, language, type(exc).__name__,
                )
                return None
            if not is_valid_audio_file(result.path):
                _remove_partial_audio(result.path)
                logger.warning("TTS synth produced empty audio (%s/%s)", name, language)
                return None
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
                path=out_path,
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


def _remove_partial_audio(path: Path) -> None:
    try:
        if path.exists() and not is_valid_audio_file(path):
            path.unlink()
    except OSError:
        pass


def _remove_audio_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
