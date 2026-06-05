from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.models import VocabularyEntry


@dataclass(frozen=True)
class DeleteOutcome:
    removed: int
    backup_path: Path | None = None


class WriteOutcome(tuple):
    """Tuple-compatible result with optional backup metadata."""

    backup_path: Path | None

    def __new__(
        cls,
        action: str,
        entry: VocabularyEntry,
        backup_path: Path | None = None,
    ):
        obj = super().__new__(cls, (action, entry))
        obj.backup_path = backup_path
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
            f"backup_path={self.backup_path!r})"
        )

    def __getnewargs__(self):
        return (self.action, self.entry, self.backup_path)
