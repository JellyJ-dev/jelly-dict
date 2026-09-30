from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.models import VocabularyEntry

LookupStatus = Literal[
    "ok",
    "not_found",
    "parse_failed",
    "network_error",
    "rate_limited",
    "unsupported",
]


@dataclass
class LookupResult:
    entry: VocabularyEntry | None = None
    status: LookupStatus = "ok"
    raw_url: str | None = None
    error_detail: str | None = None
    suggested_word: str | None = None
    related_words: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.entry is not None


@dataclass(frozen=True)
class WorkbookRevision:
    """Filesystem identity used to reject stale read-modify-write commits."""

    resolved_path: str
    exists: bool
    device: int = 0
    inode: int = 0
    size: int = 0
    mtime_ns: int = 0

    @classmethod
    def capture(cls, path: Path) -> "WorkbookRevision":
        resolved = Path(path).expanduser().resolve(strict=False)
        try:
            stat = resolved.stat()
        except FileNotFoundError:
            return cls(str(resolved), False)
        return cls(
            resolved_path=str(resolved),
            exists=True,
            device=int(stat.st_dev),
            inode=int(stat.st_ino),
            size=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
        )


@dataclass(frozen=True)
class EntryRef:
    """A stable row identity within one exact workbook revision."""

    language: str
    word_key: str
    row_number: int
    identity: str


@dataclass(frozen=True)
class EntryPatch:
    """Storage-neutral append/replace command for one vocabulary row."""

    entry_json: str
    ref: EntryRef | None = None

    @classmethod
    def replace(cls, ref: EntryRef, entry: VocabularyEntry) -> "EntryPatch":
        return cls(entry.to_json(), ref)

    @classmethod
    def append(cls, entry: VocabularyEntry) -> "EntryPatch":
        return cls(entry.to_json())

    @property
    def entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.entry_json)


@dataclass(frozen=True)
class SavePreparation:
    """Immutable read result used for a revision-checked save decision."""

    path: Path
    expected_revision: WorkbookRevision
    candidate: VocabularyEntry
    existing: VocabularyEntry | None = None
    existing_ref: EntryRef | None = None


@dataclass(frozen=True)
class ExportSourceRow:
    ref: EntryRef
    data: dict[str, Any]


@dataclass(frozen=True)
class ExportSourceSnapshot:
    path: Path
    revision: WorkbookRevision
    rows: tuple[ExportSourceRow, ...]
