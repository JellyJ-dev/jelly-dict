from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import StorageError


def backup_workbook(
    path: Path,
    reason: str = "manual",
    *,
    copy_func: Callable[[Path, Path], object] = shutil.copy2,
) -> Path:
    if not path.exists():
        raise StorageError(f"Excel file does not exist: {path}")
    safe_reason = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "-"
        for ch in (reason or "manual").strip().lower()
    ).strip("-") or "manual"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    try:
        backup_dir = path.parent / "Jelly Dict Backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{path.stem}.{safe_reason}.{timestamp}{path.suffix}"
        copy_func(path, backup_path)
    except OSError as exc:
        raise StorageError(f"Excel backup failed: {exc}") from exc
    return backup_path
