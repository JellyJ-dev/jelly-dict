from __future__ import annotations

import json
import os
import sys

from app.anki.tts.pipeline import TTSPipeline
from app.core.models import VocabularyEntry
from app.services.tts_audio_service import (
    pre_generate_entry_audio_with_pipeline,
    synthesize_text_audio,
)
from app.storage.settings_store import Settings


def main() -> int:
    _apply_background_priority()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return _emit({"ok": False, "error": "invalid json"}, code=2)

    action = payload.get("action")
    if action == "synthesize_text":
        return _synthesize_text(payload)
    if action == "pre_generate_entries":
        return _pre_generate_entries(payload)
    return _emit({"ok": False, "error": "unknown action"}, code=2)


def _synthesize_text(payload: dict) -> int:
    settings = Settings(**dict(payload.get("settings") or {}))
    text = str(payload.get("text") or "")
    language = str(payload.get("language") or "en")
    try:
        path = synthesize_text_audio(text, language, settings)
    except Exception as exc:
        return _emit({"ok": False, "error": type(exc).__name__}, code=1)
    return _emit({"ok": path is not None, "path": str(path) if path else ""})


def _pre_generate_entries(payload: dict) -> int:
    generated = 0
    pipelines: dict[tuple[object, ...], TTSPipeline] = {}
    for item in payload.get("jobs") or []:
        try:
            settings = Settings(**dict(item.get("settings") or {}))
            entry = VocabularyEntry.from_dict(dict(item.get("entry") or {}))
            key = _pipeline_key(settings)
            pipeline = pipelines.get(key)
            if pipeline is None:
                pipeline = TTSPipeline(settings)
                pipelines[key] = pipeline
            generated += pre_generate_entry_audio_with_pipeline(entry, settings, pipeline)
        except Exception:
            continue
    return _emit({"ok": True, "generated": generated})


def _pipeline_key(settings: Settings) -> tuple[object, ...]:
    return (
        settings.tts_engine_en,
        settings.tts_engine_ja,
        settings.tts_voice_en,
        settings.tts_voice_ja,
        settings.tts_bitrate,
        settings.tts_sample_rate,
        settings.excel_path_for("en"),
        settings.excel_path_for("ja"),
        settings.voicevox_url,
    )


def _apply_background_priority() -> None:
    try:
        value = int(os.environ.get("JELLY_DICT_TTS_NICE", "0") or "0")
    except ValueError:
        value = 0
    if value <= 0 or not hasattr(os, "nice"):
        return
    try:
        os.nice(value)
    except OSError:
        pass


def _emit(payload: dict, *, code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
