from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.storage.settings_store import Settings


def wav_to_mp3(wav: Path, mp3: Path, settings: "Settings") -> None:
    """Transcode WAV to mono mp3 using ffmpeg, falling back to keeping WAV."""
    if shutil.which("ffmpeg") is None:
        log.warning("ffmpeg not found; keeping WAV at %s", wav)
        try:
            mp3.unlink(missing_ok=True)
        except OSError:
            pass
        wav.replace(mp3)
        return

    bitrate = getattr(settings, "tts_bitrate", "96k")
    sr = getattr(settings, "tts_sample_rate", 44100)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(wav),
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-b:a",
        bitrate,
        str(mp3),
    ]
    try:
        subprocess.run(cmd, check=True)
    finally:
        try:
            wav.unlink()
        except OSError:
            pass
