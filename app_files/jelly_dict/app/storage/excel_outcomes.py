from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.domain import EntryRef
from app.core.models import VocabularyEntry
from app.storage.workbook_revision import WorkbookRevision
from app.storage.workbook_snapshot import RowSnapshot


@dataclass(frozen=True)
class DeleteOutcome:
    removed: int
    backup_path: Path | None = None
    rows: tuple[RowSnapshot, ...] = ()
    before_revision: WorkbookRevision | None = None
    after_revision: WorkbookRevision | None = None
    cache_snapshot: tuple[VocabularyEntry, ...] = ()
    recent_snapshot: tuple[Any, ...] = ()
    saved_projection_snapshot: tuple[Any, ...] = ()
    deferred_anki_operation_id: str | None = None


class WriteOutcome(tuple):
    """Tuple-compatible result with optional backup metadata."""

    backup_path: Path | None
    entry_ref: EntryRef | None
    revision: WorkbookRevision | None

    def __new__(
        cls,
        action: str,
        entry: VocabularyEntry,
        backup_path: Path | None = None,
        entry_ref: EntryRef | None = None,
        revision: WorkbookRevision | None = None,
    ):
        obj = super().__new__(cls, (action, entry))
        obj.backup_path = backup_path
        obj.entry_ref = entry_ref
        obj.revision = revision
        return obj

    @property
    def action(self) -> str:
        return self[0]

    @property
    def entry(self) -> VocabularyEntry:
        return self[1]

    def __repr__(self) -> str:
        return (
            f"WriteOutcome(action={self.action!r}, entry={self.entry!r}, "
            f"backup_path={self.backup_path!r}, entry_ref={self.entry_ref!r}, "
            f"revision={self.revision!r})"
        )

    def __getnewargs__(self):
        return (
            self.action,
            self.entry,
            self.backup_path,
            self.entry_ref,
            self.revision,
        )
