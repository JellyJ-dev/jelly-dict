from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.core.models import VocabularyEntry
from app.core.settings import AppSettings, SettingsDraft
from app.tts.audio_cache import is_valid_audio_file
from app.tts.audio_service import cached_audio_path_for_text, tts_configured
from app.tts.broker import (
    BACKGROUND_PRIORITY,
    INTERACTIVE_PRIORITY,
    TtsBrokerCancelled,
    get_tts_broker,
)

log = logging.getLogger(__name__)
SettingsLike = AppSettings | SettingsDraft


def synthesize_text_audio_in_process(
    text: str,
    language: str,
    settings: SettingsLike,
    *,
    timeout: int = 240,
) -> Path | None:
    cached = cached_audio_path_for_text(text, language, settings)
    if cached is not None:
        return cached
    if not tts_configured(settings, language):
        return None
    result = get_tts_broker().request(
        {
            "action": "synthesize_text",
            "text": text,
            "language": language,
            "settings": settings.to_dict(),
        },
        priority=INTERACTIVE_PRIORITY,
        timeout=timeout,
    )
    path = result.get("path")
    if not path:
        return None
    audio_path = Path(str(path)).expanduser()
    return audio_path if is_valid_audio_file(audio_path) else None


def pre_generate_entries_audio_in_process(
    jobs: list[tuple[SettingsLike, VocabularyEntry]],
    *,
    timeout: int = 900,
    cancel_event: threading.Event | None = None,
) -> int:
    generated = 0
    broker = get_tts_broker()
    for settings, entry in jobs:
        if cancel_event is not None and cancel_event.is_set():
            break
        if not tts_configured(settings, entry.language):
            continue
        try:
            result = broker.request(
                {
                    "action": "generate_entry",
                    "settings": settings.to_dict(),
                    "entry": entry.to_dict(),
                },
                priority=BACKGROUND_PRIORITY,
                timeout=timeout,
                cancel_event=cancel_event,
            )
        except TtsBrokerCancelled:
            break
        except Exception as exc:
            log.warning("TTS background broker request failed: %s", exc)
            continue
        try:
            generated += int(result.get("generated", 0))
        except (TypeError, ValueError):
            continue
    return generated
