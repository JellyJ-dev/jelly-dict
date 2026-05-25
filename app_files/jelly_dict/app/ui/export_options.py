from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.storage.settings_store import Settings

AudioPolicy = Literal["settings", "force_tts", "no_tts", "remove_audio"]
ConfirmMode = Literal["smart", "always", "never"]


@dataclass(frozen=True)
class ExportOptions:
    audio_policy: AudioPolicy = "settings"
    save_as_default: bool = False
    suppress_future_confirm: bool = False

    @property
    def removes_audio(self) -> bool:
        return self.audio_policy == "remove_audio"


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


def apply_audio_policy(settings: Settings, language: str, policy: AudioPolicy) -> Settings:
    """Return the same settings object with this export's effective audio mode.

    Callers pass a deepcopy when they do not want the user's saved settings
    changed. Keeping mutation here explicit avoids duplicating policy rules
    across the dialog, preflight, and exporter paths.
    """
    if policy == "settings":
        return settings
    if policy in ("no_tts", "remove_audio"):
        settings.tts_enabled = False
        return settings
    if policy == "force_tts":
        settings.tts_enabled = True
        engine_attr = "tts_engine_ja" if language == "ja" else "tts_engine_en"
        voice_attr = "tts_voice_ja" if language == "ja" else "tts_voice_en"
        if not getattr(settings, engine_attr, ""):
            setattr(settings, engine_attr, "kokoro")
        if not getattr(settings, voice_attr, ""):
            setattr(settings, voice_attr, "jf_alpha" if language == "ja" else "af_heart")
    return settings


def build_export_plan(
    settings: Settings,
    *,
    language: str,
    deck_name: str,
    card_count: int,
    audio_policy: AudioPolicy = "settings",
) -> ExportPlan:
    effective_tts = bool(settings.tts_enabled)
    if audio_policy in ("no_tts", "remove_audio"):
        effective_tts = False
    elif audio_policy == "force_tts":
        effective_tts = True

    engine = settings.tts_engine_ja if language == "ja" else settings.tts_engine_en
    voice = settings.tts_voice_ja if language == "ja" else settings.tts_voice_en
    return ExportPlan(
        language=language,
        deck_name=deck_name,
        card_count=card_count,
        audio_policy=audio_policy,
        effective_tts_enabled=effective_tts,
        tts_engine=engine or "none",
        tts_voice=voice or "",
        tts_play_examples=bool(settings.tts_play_examples),
        tts_play_front=bool(settings.tts_play_front),
        tts_play_back=bool(settings.tts_play_back),
    )


def should_confirm_export(
    settings: Settings,
    plan: ExportPlan,
    *,
    has_blockers: bool,
    has_warnings: bool,
    output_exists: bool,
) -> bool:
    mode = getattr(settings, "anki_export_confirm_mode", "smart") or "smart"
    if mode == "always":
        return True
    if mode == "never":
        return has_blockers
    if has_blockers or has_warnings:
        return True
    if output_exists:
        return True
    if plan.card_count == 0:
        return True
    if plan.audio_policy == "remove_audio":
        return True
    last_tts = getattr(settings, "last_apkg_export_tts_enabled", None)
    if last_tts is None:
        return True
    if last_tts is True and not plan.effective_tts_enabled:
        return True
    if plan.effective_tts_enabled and plan.tts_play_examples and plan.card_count >= 50:
        return True
    return False


def status_summary(settings: Settings, language: str) -> str:
    if not settings.tts_enabled:
        return "TTS 꺼짐"
    engine = settings.tts_engine_ja if language == "ja" else settings.tts_engine_en
    if engine == "voicevox":
        try:
            from app.anki.tts.voicevox_provider import VoicevoxProvider

            if not VoicevoxProvider.is_running(settings.voicevox_url, timeout=0.2):
                return "VOICEVOX 꺼짐"
        except Exception:
            return "VOICEVOX 확인 실패"
    return f"TTS 켜짐 · {engine or '엔진 없음'}"
