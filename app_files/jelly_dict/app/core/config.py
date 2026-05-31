from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "jelly dict"
APP_DISPLAY_NAME = "Jelly Dict"
APP_SLUG = "jelly-dict"


def project_root() -> Path:
    """Return the repository root containing app/ and .jelly_dict/."""
    return Path(__file__).resolve().parents[2]


def runtime_dir() -> Path:
    """Local runtime data directory (.jelly_dict/ inside the project root).

    Per dev.md §16-A: all runtime state stays local. Tests can override
    via the JELLY_DICT_HOME env var.
    """
    override = os.environ.get("JELLY_DICT_HOME")
    if override:
        path = Path(override).expanduser().resolve()
    else:
        path = project_root() / ".jelly_dict"
    path.mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return runtime_dir() / "settings.json"


def cache_db_path() -> Path:
    return runtime_dir() / "cache.db"


def log_path() -> Path:
    return runtime_dir() / "logs" / "app.log"


def quickstart_state_path() -> Path:
    return project_root() / ".quickstart_ok"


def default_excel_dir() -> Path:
    return Path.home() / "Documents" / APP_SLUG


def default_excel_path() -> Path:
    return default_excel_dir() / "vocab.xlsx"


def tts_cache_dir() -> Path:
    path = runtime_dir() / "tts_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Domain whitelist enforced by the Playwright client.
ALLOWED_DOMAINS: tuple[str, ...] = (
    "naver.com",
    "dict.naver.com",
    "en.dict.naver.com",
    "ja.dict.naver.com",
    "pstatic.net",  # naver static (audio etc.)
    "phinf.pstatic.net",
    # OCR — Google Cloud Vision (only when user enabled with own key)
    "vision.googleapis.com",
)


def is_domain_allowed(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    for allowed in ALLOWED_DOMAINS:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False
