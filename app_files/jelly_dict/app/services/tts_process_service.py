from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.models import VocabularyEntry
from app.anki.tts.cache import is_valid_audio_file
from app.services.tts_audio_service import cached_audio_path_for_text, tts_configured
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[2]


def synthesize_text_audio_in_process(
    text: str,
    language: str,
    settings: Settings,
    *,
    timeout: int = 240,
) -> Path | None:
    cached = cached_audio_path_for_text(text, language, settings)
    if cached is not None:
        return cached
    if not tts_configured(settings, language):
        return None

    result = _run_worker(
        {
            "action": "synthesize_text",
            "text": text,
            "language": language,
            "settings": settings.to_dict(),
        },
        timeout=timeout,
    )
    path = result.get("path") if isinstance(result, dict) else ""
    if not path:
        return None
    audio_path = Path(str(path)).expanduser()
    return audio_path if is_valid_audio_file(audio_path) else None


def pre_generate_entries_audio_in_process(
    jobs: list[tuple[Settings, VocabularyEntry]],
    *,
    timeout: int = 900,
) -> int:
    payload_jobs = [
        {"settings": settings.to_dict(), "entry": entry.to_dict()}
        for settings, entry in jobs
        if tts_configured(settings, entry.language)
    ]
    if not payload_jobs:
        return 0

    result = _run_worker(
        {"action": "pre_generate_entries", "jobs": payload_jobs},
        timeout=timeout,
    )
    try:
        return int(result.get("generated", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _run_worker(payload: dict, *, timeout: int) -> dict:
    python = _python_command()
    if not python:
        log.warning("TTS subprocess skipped: Python executable not found")
        return {}

    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["JELLY_DICT_TTS_NICE"] = env.get("JELLY_DICT_TTS_NICE", "10")
    python_path = env.get("PYTHONPATH", "")
    app_root = str(_APP_ROOT)
    env["PYTHONPATH"] = app_root if not python_path else f"{app_root}{os.pathsep}{python_path}"

    try:
        completed = subprocess.run(
            [python, "-m", "app.services.tts_worker_process"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=str(_APP_ROOT),
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("TTS subprocess timed out for action %s", payload.get("action"))
        return {}
    except OSError as exc:
        log.warning("TTS subprocess failed to start: %s", exc)
        return {}

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()[-1:]
        log.warning(
            "TTS subprocess failed (%s): %s",
            completed.returncode,
            stderr[0] if stderr else "",
        )
        return {}
    try:
        data = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        log.warning("TTS subprocess returned invalid JSON")
        return {}
    return data if isinstance(data, dict) else {}


def _python_command() -> str:
    env_python = os.environ.get("JELLY_DICT_PYTHON", "").strip()
    if env_python and Path(env_python).exists():
        return env_python

    executable = getattr(sys, "executable", "") or ""
    if executable and Path(executable).exists():
        return executable

    venv = os.environ.get("VIRTUAL_ENV", "").strip()
    if venv:
        candidate = Path(venv) / "bin" / "python"
        if candidate.exists():
            return str(candidate)

    for name in ("python3.12", "python3.11", "python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return ""
