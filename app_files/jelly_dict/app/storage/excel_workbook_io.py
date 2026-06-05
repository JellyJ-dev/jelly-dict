from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

from app.core.errors import ExcelFormatError, ExcelLockedError, StorageError

log = logging.getLogger(__name__)


def load_for_write(path: Path) -> Workbook:
    try:
        return load_workbook(path)
    except OSError as exc:
        raise ExcelLockedError(str(exc)) from exc
    except Exception as exc:
        raise ExcelFormatError(str(exc)) from exc


def save_workbook(wb: Workbook, path: Path) -> None:
    temp_name = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            delete=False,
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=path.suffix,
        ) as temp_file:
            temp_name = temp_file.name
        temp_path = Path(temp_name)
        wb.save(temp_path)
        copy_existing_permissions(path, temp_path)
        temp_path.replace(path)
    except PermissionError as exc:
        raise ExcelLockedError(str(exc)) from exc
    except OSError as exc:
        raise StorageError(str(exc)) from exc
    finally:
        if temp_name:
            temp_path = Path(temp_name)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    log.warning("failed to clean temporary workbook: %s", temp_path)


def copy_existing_permissions(source: Path, target: Path) -> None:
    if not source.exists():
        return
    try:
        shutil.copymode(source, target)
    except OSError:
        log.warning("failed to preserve workbook permissions: %s", source)


def raise_with_backup_hint(exc: StorageError, backup_path: Path) -> None:
    message = f"{exc}\n백업 파일: {backup_path}"
    if isinstance(exc, ExcelLockedError):
        raise ExcelLockedError(message) from exc
    raise StorageError(message) from exc
