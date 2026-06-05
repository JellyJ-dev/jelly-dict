from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AudioPolicy = Literal["settings", "force_tts", "no_tts", "remove_audio"]


@dataclass(frozen=True)
class ExportPlan:
    language: str
    deck_name: str
    card_count: int
    audio_policy: AudioPolicy
    effective_tts_enabled: bool
    tts_engine: str
    tts_voice: str
    tts_play_examples: bool
    tts_play_front: bool
    tts_play_back: bool

    @property
    def audio_summary(self) -> str:
        if self.audio_policy == "remove_audio":
            return "Anki 카드 음성 비우기"
        if not self.effective_tts_enabled:
            return "TTS 없음"
        examples = "단어+예문 음성" if self.tts_play_examples else "단어 음성"
        return f"TTS 포함 · {self.tts_engine} · {examples}"


def language_label(language: str) -> str:
    return "일본어" if language == "ja" else "영어"
