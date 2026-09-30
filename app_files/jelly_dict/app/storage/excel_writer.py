"""Write-side helpers for the vocabulary Excel file.

Reader and serializer concerns live in `excel_reader.py` and
`excel_serializer.py` respectively. For backward compatibility this
module re-exports their public symbols so existing callers like
``from app.storage import excel_writer; excel_writer.list_entries(...)``
keep working without import changes.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from openpyxl import Workbook

from app.core.models import VocabularyEntry
from app.storage.excel_backup import backup_workbook as _backup_workbook
from app.storage.excel_outcomes import DeleteOutcome, WriteOutcome
from app.storage.excel_reader import (
    WorkbookReadResult,
    WorkbookReadState,
    find_existing,
    list_entries,
    list_entries_strict,
    read_entries_result,
)
from app.storage.excel_repository import EntryPatch, WorkbookRepository
from app.storage.excel_schema import write_header as _write_header
from app.storage.excel_serializer import (
    COLUMN_LABELS,
    COLUMN_WIDTHS,
    HEADER_FILL,
    HEADER_FONT,
    SHEET_NAME,
)
from app.storage.excel_workbook_io import (
    load_for_write as _load_for_write,
)
from app.storage.excel_workbook_io import (
    save_workbook,
)
from app.storage.workbook_revision import WorkbookRevision

_save = save_workbook
SaveResolver = Callable[[VocabularyEntry | None, VocabularyEntry], tuple[str, VocabularyEntry]]

# Re-exports: keep the existing public surface identical.
__all__ = [
    "SHEET_NAME",
    "COLUMN_LABELS",
    "COLUMN_WIDTHS",
    "HEADER_FILL",
    "HEADER_FONT",
    "DeleteOutcome",
    "WriteOutcome",
    "ensure_workbook",
    "append_entry",
    "update_or_append",
    "backup_workbook",
    "delete_entries",
    "delete_entries_with_backup",
    "replace_entry",
    "save_with_resolver",
    "list_entries",
    "find_existing",
    "list_entries_strict",
    "read_entries_result",
    "WorkbookReadResult",
    "WorkbookReadState",
]


def ensure_workbook(path: Path, columns: list[str]) -> None:
    """Create the file with header row if it does not already exist."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    try:
        ws = wb.active
        ws.title = SHEET_NAME
        _write_header(ws, columns)
        _save(wb, path)
    finally:
        wb.close()


def append_entry(path: Path, entry: VocabularyEntry, columns: list[str]) -> None:
    """Append a single entry. Creates the file if missing."""
    repository = _repository()
    revision = WorkbookRevision.capture(path)
    repository.commit_patch_without_snapshot(
        path,
        revision,
        [EntryPatch.append(entry)],
        columns,
    )


def update_or_append(path: Path, entry: VocabularyEntry, columns: list[str]) -> None:
    """Replace an existing row with the same (language, word) or append."""
    repository = _repository()
    snapshot = repository.read_snapshot(path)
    existing = snapshot.find_key(entry.language, entry.word_key())
    patch = (
        EntryPatch.replace(existing.ref, entry)
        if existing is not None
        else EntryPatch.append(entry)
    )
    repository.commit_patch_without_snapshot(
        path,
        snapshot.revision,
        [patch],
        columns,
    )


def backup_workbook(path: Path, reason: str = "manual") -> Path:
    return _backup_workbook(path, reason, copy_func=shutil.copy2)


def _repository() -> WorkbookRepository:
    return WorkbookRepository(
        load_func=_load_for_write,
        save_func=_save,
        backup_func=backup_workbook,
    )


def delete_entries(path: Path, language: str, word_keys: set[str]) -> int:
    return delete_entries_with_backup(
        path,
        language,
        word_keys,
        create_backup=False,
    ).removed


def delete_entries_with_backup(
    path: Path,
    language: str,
    word_keys: set[str],
    *,
    create_backup: bool = True,
) -> DeleteOutcome:
    repository = _repository()
    revision = WorkbookRevision.capture(path)
    outcome = repository.delete_matching_rows(
        path,
        revision,
        language,
        word_keys,
        create_backup=create_backup,
    )
    return DeleteOutcome(
        removed=outcome.removed,
        backup_path=outcome.backup_path,
        rows=outcome.rows,
        before_revision=outcome.before_revision,
        after_revision=outcome.after_revision,
    )


def replace_entry(
    path: Path,
    language: str,
    original_word_key: str,
    entry: VocabularyEntry,
    columns: list[str],
    *,
    create_backup: bool = True,
) -> WriteOutcome:
    repository = _repository()
    snapshot = repository.read_snapshot(path)
    existing = snapshot.find_key(language, original_word_key)
    if existing is None:
        committed = repository.commit_patch_without_snapshot(
            path,
            snapshot.revision,
            [EntryPatch.append(entry)],
            columns,
        )
        return WriteOutcome(
            "create",
            entry,
            entry_ref=committed.affected_refs[0],
            revision=committed.after_revision,
        )
    patch = EntryPatch.replace(existing.ref, entry)
    if create_backup:
        committed = repository.commit_patch_with_backup(
            path,
            snapshot.revision,
            [patch],
            columns,
            backup_reason=f"edit-{language}",
            refresh_snapshot=False,
        )
        return WriteOutcome(
            "overwrite",
            entry,
            committed.backup_path,
            committed.affected_refs[0],
            committed.after_revision,
        )
    committed = repository.commit_patch_without_snapshot(
        path,
        snapshot.revision,
        [patch],
        columns,
    )
    return WriteOutcome(
        "overwrite",
        entry,
        entry_ref=committed.affected_refs[0],
        revision=committed.after_revision,
    )


def save_with_resolver(
    path: Path,
    entry: VocabularyEntry,
    columns: list[str],
    resolver: SaveResolver,
    *,
    backup_on_overwrite: bool = False,
) -> WriteOutcome:
    """Save one entry using an explicit duplicate-resolution action."""
    repository = _repository()
    snapshot = repository.read_snapshot(path)
    existing = snapshot.find_key(entry.language, entry.word_key())
    existing_entry = existing.entry if existing is not None else None
    action, resolved = resolver(existing_entry, entry)
    if action == "skip":
        return WriteOutcome(
            action,
            existing_entry or entry,
            entry_ref=existing.ref if existing is not None else None,
            revision=snapshot.revision,
        )
    patch = (
        EntryPatch.replace(existing.ref, resolved)
        if action == "overwrite" and existing is not None
        else EntryPatch.append(resolved)
    )
    if action == "overwrite" and existing is not None and backup_on_overwrite:
        committed = repository.commit_patch_with_backup(
            path,
            snapshot.revision,
            [patch],
            columns,
            backup_reason=f"overwrite-{entry.language}",
            refresh_snapshot=False,
        )
        return WriteOutcome(
            action,
            resolved,
            committed.backup_path,
            committed.affected_refs[0],
            committed.after_revision,
        )
    committed = repository.commit_patch_without_snapshot(
        path,
        snapshot.revision,
        [patch],
        columns,
    )
    return WriteOutcome(
        action,
        resolved,
        entry_ref=committed.affected_refs[0],
        revision=committed.after_revision,
    )
