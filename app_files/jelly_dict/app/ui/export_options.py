from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.export_plan import AudioPolicy, ExportPlan, language_label
from app.core.settings import AppSettings, SettingsDraft, settings_snapshot

ConfirmMode = Literal["smart", "always", "never"]

__all__ = [
    "AudioPolicy",
    "ConfirmMode",
    "ExportOptions",
    "ExportPlan",
    "apply_audio_policy",
    "build_export_plan",
    "language_label",
    "should_confirm_export",
]


@dataclass(frozen=True)
class ExportOptions:
    audio_policy: AudioPolicy = "settings"
    save_as_default: bool = False
    suppress_future_confirm: bool = False

    @property
    def removes_audio(self) -> bool:
        return self.audio_policy == "remove_audio"


def apply_audio_policy(
    settings: AppSettings | SettingsDraft,
    language: str,
    policy: AudioPolicy,
) -> AppSettings:
    """Return an immutable snapshot with the requested audio policy."""
    snapshot = settings_snapshot(settings)
    if policy == "settings":
        return snapshot
    if policy in ("no_tts", "remove_audio"):
        return snapshot.with_changes(tts_enabled=False)
    if policy == "force_tts":
        changes = {"tts_enabled": True}
        engine_attr = "tts_engine_ja" if language == "ja" else "tts_engine_en"
        voice_attr = "tts_voice_ja" if language == "ja" else "tts_voice_en"
        if not getattr(snapshot, engine_attr, ""):
            changes[engine_attr] = "kokoro"
        if not getattr(snapshot, voice_attr, ""):
            changes[voice_attr] = "jf_alpha" if language == "ja" else "af_heart"
        return snapshot.with_changes(**changes)
    return snapshot


def build_export_plan(
    settings: AppSettings | SettingsDraft,
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
    settings: AppSettings | SettingsDraft,
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


def status_summary(settings: AppSettings | SettingsDraft, language: str) -> str:
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
