"""Filename-based TTS cache.

A given (language, engine, voice, text, output settings) combination always
produces the same path on disk. The first generation writes the mp3; every
subsequent request reuses it.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.core import config


_VOICE_SAFE = re.compile(r"[^A-Za-z0-9_\-]+")


def cache_path(
    language: str,
    engine: str,
    voice: str,
    text: str,
    *,
    bitrate: str = "",
    sample_rate: int | str | None = None,
) -> Path:
    """Return the deterministic cache path for the given input."""
    safe_voice = _VOICE_SAFE.sub("-", voice or "default")
    cache_key = "\n".join(
        [text, f"bitrate={bitrate or ''}", f"sample_rate={sample_rate or ''}"]
    )
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:12]
    name = f"{language}_{engine}_{safe_voice}_{digest}.mp3"
    return config.tts_cache_dir() / name


def has_cached(
    language: str,
    engine: str,
    voice: str,
    text: str,
    *,
    bitrate: str = "",
    sample_rate: int | str | None = None,
) -> bool:
    return cache_path(
        language, engine, voice, text, bitrate=bitrate, sample_rate=sample_rate
    ).exists()


def is_valid_audio_file(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def clear_cache() -> int:
    """Remove all cached mp3 files. Returns count removed."""
    base = config.tts_cache_dir()
    count = 0
    for f in base.glob("*.mp3"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    return count
