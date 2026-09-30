"""Compatibility facade for :mod:`app.tts.audio_service`."""

from __future__ import annotations

import importlib

__all__ = [
    "cached_audio_path_for_text",
    "expected_audio_path_for_text",
    "pre_generate_entry_audio",
    "pre_generate_entry_audio_with_pipeline",
    "synthesize_text_audio",
    "synthesize_word_audio",
    "tts_configured",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    value = getattr(importlib.import_module("app.tts.audio_service"), name)
    globals()[name] = value
    return value
