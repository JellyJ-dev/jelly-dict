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
    cache_dir: Path | None = None,
) -> Path:
    """Return the deterministic cache path for the given input."""
    safe_voice = _VOICE_SAFE.sub("-", voice or "default")
    cache_key = "\n".join(
        [text, f"bitrate={bitrate or ''}", f"sample_rate={sample_rate or ''}"]
    )
    digest = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:12]
    name = f"{language}_{engine}_{safe_voice}_{digest}.mp3"
    base = cache_dir or config.tts_cache_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / name


def has_cached(
    language: str,
    engine: str,
    voice: str,
    text: str,
    *,
    bitrate: str = "",
    sample_rate: int | str | None = None,
    cache_dir: Path | None = None,
) -> bool:
    return cache_path(
        language,
        engine,
        voice,
        text,
        bitrate=bitrate,
        sample_rate=sample_rate,
        cache_dir=cache_dir,
    ).exists()


def wordbook_audio_dir(settings, language: str) -> Path:
    """Return the per-wordbook mp3 folder for generated TTS audio."""
    try:
        raw_path = settings.excel_path_for(language)
    except Exception:
        return config.tts_cache_dir()
    if not str(raw_path or "").strip():
        return config.tts_cache_dir()
    excel_path = Path(raw_path).expanduser()
    base = excel_path.parent if excel_path.name else excel_path
    path = base / "mp3"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_valid_audio_file(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 16:
            return False
        with path.open("rb") as f:
            header = f.read(4096)
    except OSError:
        return False
    return _looks_like_mp3(header) or _looks_like_wav(header)


def _looks_like_mp3(header: bytes) -> bool:
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True
    if not header.startswith(b"ID3") or len(header) < 12:
        return False
    tag_size = _id3_synchsafe_size(header[6:10]) if len(header) >= 10 else None
    search_start = 10 + (tag_size or 0)
    window = header[search_start:] or header[10:]
    return _contains_mp3_frame_sync(window)


def _id3_synchsafe_size(raw: bytes) -> int | None:
    if len(raw) != 4 or any(byte & 0x80 for byte in raw):
        return None
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def _contains_mp3_frame_sync(data: bytes) -> bool:
    for idx in range(max(0, len(data) - 1)):
        if data[idx] == 0xFF and (data[idx + 1] & 0xE0) == 0xE0:
            return True
    return False


def _looks_like_wav(header: bytes) -> bool:
    if not (header.startswith(b"RIFF") and header[8:12] == b"WAVE"):
        return False
    return b"fmt " in header[12:] and b"data" in header[12:]


def clear_cache(cache_dirs: list[Path] | tuple[Path, ...] | set[Path] | None = None) -> int:
    """Remove all cached mp3 files. Returns count removed."""
    count = 0
    bases = list(cache_dirs) if cache_dirs is not None else [config.tts_cache_dir()]
    seen: set[Path] = set()
    for base in bases:
        try:
            base = Path(base).expanduser()
        except TypeError:
            continue
        if base in seen:
            continue
        seen.add(base)
        for f in base.glob("*.mp3"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
    return count
