"""Compatibility facade for :mod:`app.tts.process_service`."""

from __future__ import annotations

import importlib

__all__ = [
    "pre_generate_entries_audio_in_process",
    "synthesize_text_audio_in_process",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    value = getattr(importlib.import_module("app.tts.process_service"), name)
    globals()[name] = value
    return value
