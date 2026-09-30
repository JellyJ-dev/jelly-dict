"""TTS provider abstractions and shared dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TTSResult:
    """Outcome of synthesising one chunk of text."""

    path: Path  # absolute mp3 path on disk
    engine_id: str  # "kokoro" / "voicevox" / "edge"
    voice: str
    requires_credit: bool
    credit_text: str = ""  # only meaningful when requires_credit
    license_note: str = ""


@dataclass(frozen=True)
class ProviderInfo:
    """Static metadata used by the settings UI."""

    id: str
    display_name: str
    available: bool
    voices_en: tuple[str, ...]
    voices_ja: tuple[str, ...]
    requires_credit: bool
    license_note: str
    usage_warning: str = ""


@runtime_checkable
class TTSProvider(Protocol):
    @classmethod
    def info(cls) -> ProviderInfo: ...

    @classmethod
    def is_available(cls) -> bool: ...

    def synthesize(
        self,
        text: str,
        *,
        language: str,  # "en" | "ja"
        voice: str,
        out_path: Path,
    ) -> TTSResult:
        """Generate audio for ``text`` and write it to ``out_path`` (mp3).

        Implementations may write WAV first and then transcode; the final
        file at ``out_path`` must be the format requested by the caller.
        Implementations must NEVER log the API keys or full request URLs
        with keys in them.
        """


class NoTTSProvider:
    """Sentinel provider used when TTS is disabled or unavailable.

    Calling ``synthesize`` raises so the pipeline knows to skip audio for
    that entry — never crash the export.
    """

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            id="none",
            display_name="사용 안 함",
            available=True,
            voices_en=(),
            voices_ja=(),
            requires_credit=False,
            license_note="",
        )

    @classmethod
    def is_available(cls) -> bool:
        return True

    def synthesize(self, text, *, language, voice, out_path) -> TTSResult:
        raise RuntimeError("TTS is disabled")
