"""VOICEVOX TTS provider.

VOICEVOX engine is NOT bundled with jelly_dict. We only call its local
HTTP API at 127.0.0.1:50021. Generated voices require attribution
("VOICEVOX:캐릭터명") per their character-specific terms of use.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from app.anki.tts.base import ProviderInfo, TTSResult
from app.anki.tts.transcode import wav_to_mp3
from app.core.url_safety import require_loopback_http_url

if TYPE_CHECKING:
    from app.storage.settings_store import Settings

# Curated default set. Only standard (`ノーマル`) styles, picking
# personalities suitable for general listening — anything sexy/whisper/
# tsuntsun-coded is excluded. Users can extend this via the "+" picker
# in the settings UI when the engine is running.
CURATED_VOICES_JA: tuple[str, ...] = (
    "3:ずんだもん (ノーマル)",
    "2:四国めたん (ノーマル)",
    "8:春日部つむぎ (ノーマル)",
    "13:青山龍星 (ノーマル)",
    "16:九州そら (ノーマル)",
)
# Korean tone descriptions surfaced in the voice combo display. Keys are
# the canonical "<id>:<character> (<style>)" form stored in settings.
# Adding entries here only changes display labels — saved data and
# credit text stay canonical.
TONE_HINTS_JA: dict[str, str] = {
    "3:ずんだもん (ノーマル)": "밝은 소년",
    "2:四国めたん (ノーマル)": "차분한 여성",
    "8:春日部つむぎ (ノーマル)": "발랄한 여학생",
    "13:青山龍星 (ノーマル)": "단단한 남성",
    "16:九州そら (ノーマル)": "차분한 성인 여성",
}


def display_label(voice: str) -> str:
    """Return the user-facing label for a voice — appends a Korean tone
    description when one is registered for this canonical voice."""
    hint = TONE_HINTS_JA.get(voice)
    return f"{voice} — {hint}" if hint else voice


# Backwards-compat alias — older code paths refer to DEFAULT_VOICES_JA.
DEFAULT_VOICES_JA: tuple[str, ...] = CURATED_VOICES_JA


class VoicevoxProvider:
    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            id="voicevox",
            display_name="VOICEVOX (로컬 엔진)",
            available=cls.is_available(),
            voices_en=(),
            voices_ja=DEFAULT_VOICES_JA,
            requires_credit=True,
            license_note="캐릭터별 이용규약 확인 필요 — voicevox.hiroshiba.jp",
            usage_warning="공유 시 'VOICEVOX:캐릭터명' 크레딧 표기 의무",
        )

    @classmethod
    def is_available(cls) -> bool:
        # Static availability — the *binary* doesn't ship with us and we
        # don't probe the network at import time (dev.md §16-A). Live
        # liveness is checked on demand via :meth:`is_running`.
        return True

    @classmethod
    def is_running(cls, url: str = "http://127.0.0.1:50021", timeout: float = 0.5) -> bool:
        """Probe the local VOICEVOX engine. localhost only — does not
        violate the no-external-network policy."""
        import urllib.error
        import urllib.request

        try:
            require_loopback_http_url(url, "VOICEVOX")
            req = urllib.request.Request(f"{url.rstrip('/')}/version")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except (ValueError, urllib.error.URLError, OSError, TimeoutError):
            return False

    @classmethod
    def fetch_voices(
        cls,
        url: str = "http://127.0.0.1:50021",
        timeout: float = 2.0,
    ) -> tuple[str, ...]:
        """Pull the live speaker/style list from the engine.

        Returns voice strings in the ``"<style_id>:<character> (<style>)"``
        format expected by ``synthesize``. Falls back to the static
        :data:`DEFAULT_VOICES_JA` when the engine isn't reachable.
        """
        import json
        import urllib.error
        import urllib.request

        try:
            require_loopback_http_url(url, "VOICEVOX")
            req = urllib.request.Request(f"{url.rstrip('/')}/speakers")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return DEFAULT_VOICES_JA
                speakers = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return DEFAULT_VOICES_JA

        out: list[tuple[int, str]] = []
        for sp in speakers:
            name = sp.get("name", "?")
            for style in sp.get("styles", []):
                sid = style.get("id")
                style_name = style.get("name", "")
                if sid is None:
                    continue
                label = f"{sid}:{name}"
                if style_name:
                    label += f" ({style_name})"
                out.append((sid, label))
        out.sort(key=lambda t: t[0])
        return tuple(label for _, label in out) or DEFAULT_VOICES_JA

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._url = require_loopback_http_url(
            getattr(settings, "voicevox_url", "http://127.0.0.1:50021"),
            "VOICEVOX",
        ).rstrip("/")

    def _speaker_id(self, voice: str) -> int:
        # Voice format is "<id>:<display>" — parse the id.
        head = (voice or "").split(":", 1)[0].strip()
        if not head.isdigit():
            raise ValueError(f"VOICEVOX 음성 형식이 올바르지 않습니다: {voice}")
        return int(head)

    def synthesize(
        self,
        text: str,
        *,
        language: str,
        voice: str,
        out_path: Path,
    ) -> TTSResult:
        if language != "ja":
            raise ValueError("VOICEVOX는 일본어만 지원합니다.")
        speaker = self._speaker_id(voice)

        query = urllib.parse.urlencode({"text": text, "speaker": speaker})
        # 1. audio_query
        req = urllib.request.Request(
            f"{self._url}/audio_query?{query}",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            audio_query = json.loads(resp.read().decode("utf-8"))

        # 2. synthesis
        body = json.dumps(audio_query).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/synthesis?speaker={speaker}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            wav_bytes = resp.read()

        wav_path = out_path.with_suffix(".wav")
        wav_path.write_bytes(wav_bytes)
        wav_to_mp3(wav_path, out_path, self._settings)

        # Display name (after the colon) for credit text, falling back to id.
        display = voice.split(":", 1)[1].strip() if ":" in voice else voice
        return TTSResult(
            path=out_path,
            engine_id="voicevox",
            voice=voice,
            requires_credit=True,
            credit_text=f"VOICEVOX:{display}",
            license_note="VOICEVOX 캐릭터별 이용규약",
        )
