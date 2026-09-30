from __future__ import annotations

import logging
from pathlib import Path

from app.core import config

log = logging.getLogger(__name__)

TEMP_DIR_NAME = "ocr_clipboard"


def temp_dir(base: Path | None = None) -> Path:
    root = base if base is not None else config.runtime_dir()
    return root / TEMP_DIR_NAME


def remove_temp_file(path: Path | str | None) -> None:
    if path is None:
        return
    try:
        target = Path(path)
        if target.exists() and target.is_file():
            target.unlink()
    except OSError as exc:
        log.warning("ocr temp remove failed: %s", exc)


def cleanup_temp_dir(base: Path | None = None) -> int:
    directory = temp_dir(base)
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob("paste-*.png"):
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            log.warning("ocr temp cleanup failed: %s", exc)
    return removed
