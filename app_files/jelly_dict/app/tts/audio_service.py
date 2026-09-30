from __future__ import annotations

from pathlib import Path

from app.anki.tts.pipeline import TTSPipeline
from app.core.diagnostics import diagnostic_operation
from app.core.models import VocabularyEntry, collect_examples_flat
from app.core.settings import Settings
from app.tts.audio_cache import (
    cache_path,
    cached_path,
    wordbook_audio_dir,
)


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
    with diagnostic_operation("tts") as diagnostic:
        if not tts_configured(settings, entry.language):
            diagnostic.finish("skipped")
            return None
        pipeline = pipeline or TTSPipeline(settings)
        result = pipeline.synthesize(entry.word, entry.language)
        diagnostic.finish("success" if result is not None else "failed")
        return result


def synthesize_text_audio(
    text: str,
    language: str,
    settings: Settings,
    *,
    pipeline: TTSPipeline | None = None,
) -> Path | None:
    with diagnostic_operation("tts") as diagnostic:
        if not tts_configured(settings, language):
            diagnostic.finish("skipped")
            return None
        pipeline = pipeline or TTSPipeline(settings)
        result = pipeline.synthesize(text, language)
        diagnostic.finish("success" if result is not None else "failed")
        return result


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
    if not text or not text.strip() or not tts_configured(settings, language):
        return None
    return cached_path(
        language,
        _engine_for(settings, language),
        _voice_for(settings, language),
        text,
        bitrate=getattr(settings, "tts_bitrate", ""),
        sample_rate=getattr(settings, "tts_sample_rate", None),
        cache_dir=wordbook_audio_dir(settings, language),
    )


def pre_generate_entry_audio(entry: VocabularyEntry, settings: Settings) -> int:
    if not tts_configured(settings, entry.language):
        with diagnostic_operation("tts") as diagnostic:
            diagnostic.finish("skipped", row_count=0)
        return 0
    pipeline = TTSPipeline(settings)
    return pre_generate_entry_audio_with_pipeline(entry, settings, pipeline)


def pre_generate_entry_audio_with_pipeline(
    entry: VocabularyEntry,
    settings: Settings,
    pipeline: TTSPipeline,
) -> int:
    with diagnostic_operation("tts") as diagnostic:
        if not tts_configured(settings, entry.language):
            diagnostic.finish("skipped", row_count=0)
            return 0
        generated = 0
        if pipeline.synthesize(entry.word, entry.language) is not None:
            generated += 1
        if getattr(settings, "tts_play_examples", False):
            for example in entry.examples_flat or collect_examples_flat(entry):
                text = (example.source_text_plain or example.source_text or "").strip()
                if text and pipeline.synthesize(text, entry.language) is not None:
                    generated += 1
        diagnostic.finish("empty" if not generated else "success", row_count=generated)
        return generated


def _engine_for(settings: Settings, language: str) -> str:
    return settings.tts_engine_ja if language == "ja" else settings.tts_engine_en


def _voice_for(settings: Settings, language: str) -> str:
    return settings.tts_voice_ja if language == "ja" else settings.tts_voice_en
