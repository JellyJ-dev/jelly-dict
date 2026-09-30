from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

from app.core.diagnostics import diagnostic_operation
from app.core.errors import ExcelFormatError, ExcelLockedError, StorageError
from app.storage.workbook_recovery_journal import WorkbookRecoveryJournal
from app.storage.workbook_revision import WorkbookRevision

log = logging.getLogger(__name__)


def load_for_write(path: Path) -> Workbook:
    try:
        return load_workbook(path)
    except OSError as exc:
        raise ExcelLockedError(str(exc)) from exc
    except Exception as exc:
        raise ExcelFormatError(str(exc)) from exc


def save_workbook(
    wb: Workbook,
    path: Path,
    *,
    before_revision: WorkbookRevision | None = None,
    backup_path: Path | None = None,
    recovery_journal: WorkbookRecoveryJournal | None = None,
) -> None:
    with diagnostic_operation("workbook_write") as diagnostic:
        _save_workbook(
            wb,
            path,
            before_revision=before_revision,
            backup_path=backup_path,
            recovery_journal=recovery_journal,
        )
        diagnostic.finish("success", row_count=_workbook_row_count(wb))


def _save_workbook(
    wb: Workbook,
    path: Path,
    *,
    before_revision: WorkbookRevision | None,
    backup_path: Path | None,
    recovery_journal: WorkbookRecoveryJournal | None,
) -> None:
    path = Path(path).expanduser().resolve(strict=False)
    temp_name = ""
    transaction = (recovery_journal or WorkbookRecoveryJournal()).begin(
        path,
        before_revision or WorkbookRevision.capture(path),
        backup_path,
    )
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
        transaction.temp_created(temp_path)
        wb.save(temp_path)
        copy_existing_permissions(path, temp_path)
        with temp_path.open("rb") as saved_file:
            os.fsync(saved_file.fileno())
        transaction.ready_to_commit(temp_path)
        temp_path.replace(path)
        transaction.committed(WorkbookRevision.capture(path))
    except PermissionError as exc:
        transaction.failed(exc)
        raise ExcelLockedError(str(exc)) from exc
    except OSError as exc:
        transaction.failed(exc)
        raise StorageError(str(exc)) from exc
    except Exception as exc:
        transaction.failed(exc)
        raise
    finally:
        if temp_name:
            temp_path = Path(temp_name)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    log.warning("failed to clean temporary workbook: %s", temp_path)


def _workbook_row_count(workbook: Workbook) -> int:
    return sum(max(0, sheet.max_row - 1) for sheet in workbook.worksheets)


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
