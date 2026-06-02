from __future__ import annotations

from pathlib import Path

from app.anki.tts.pipeline import TTSPipeline
from app.anki.tts.cache import cache_path, is_valid_audio_file, wordbook_audio_dir
from app.core.models import VocabularyEntry, collect_examples_flat
from app.storage.settings_store import Settings


def tts_configured(settings: Settings | None, language: str) -> bool:
    if settings is None or not getattr(settings, "tts_enabled", False):
        return False
    engine = _engine_for(settings, language)
    voice = _voice_for(settings, language)
    return bool(engine and engine != "none" and voice)


def synthesize_word_audio(
    entry: VocabularyEntry,
    settings: Settings,
    *,
    pipeline: TTSPipeline | None = None,
) -> Path | None:
    if not tts_configured(settings, entry.language):
        return None
    pipeline = pipeline or TTSPipeline(settings)
    return pipeline.synthesize(entry.word, entry.language)


def synthesize_text_audio(
    text: str,
    language: str,
    settings: Settings,
    *,
    pipeline: TTSPipeline | None = None,
) -> Path | None:
    if not tts_configured(settings, language):
        return None
    pipeline = pipeline or TTSPipeline(settings)
    return pipeline.synthesize(text, language)


def expected_audio_path_for_text(
    text: str,
    language: str,
    settings: Settings,
) -> Path | None:
    if not text or not text.strip() or not tts_configured(settings, language):
        return None
    engine = _engine_for(settings, language)
    voice = _voice_for(settings, language)
    return cache_path(
        language,
        engine,
        voice,
        text,
        bitrate=getattr(settings, "tts_bitrate", ""),
        sample_rate=getattr(settings, "tts_sample_rate", None),
        cache_dir=wordbook_audio_dir(settings, language),
    )


def cached_audio_path_for_text(
    text: str,
    language: str,
    settings: Settings,
) -> Path | None:
    path = expected_audio_path_for_text(text, language, settings)
    if path is not None and is_valid_audio_file(path):
        return path
    return None


def pre_generate_entry_audio(entry: VocabularyEntry, settings: Settings) -> int:
    if not tts_configured(settings, entry.language):
        return 0
    pipeline = TTSPipeline(settings)
    return pre_generate_entry_audio_with_pipeline(entry, settings, pipeline)


def pre_generate_entry_audio_with_pipeline(
    entry: VocabularyEntry,
    settings: Settings,
    pipeline: TTSPipeline,
) -> int:
    if not tts_configured(settings, entry.language):
        return 0
    generated = 0
    if pipeline.synthesize(entry.word, entry.language) is not None:
        generated += 1
    if getattr(settings, "tts_play_examples", False):
        for example in entry.examples_flat or collect_examples_flat(entry):
            text = (example.source_text_plain or example.source_text or "").strip()
            if text and pipeline.synthesize(text, entry.language) is not None:
                generated += 1
    return generated


def _engine_for(settings: Settings, language: str) -> str:
    return settings.tts_engine_ja if language == "ja" else settings.tts_engine_en


def _voice_for(settings: Settings, language: str) -> str:
    return settings.tts_voice_ja if language == "ja" else settings.tts_voice_en
