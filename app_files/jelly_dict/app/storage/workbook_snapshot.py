from __future__ import annotations

import hashlib
import json
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from openpyxl.cell.cell import Cell

from app.core.domain import EntryRef
from app.core.models import VocabularyEntry, normalize_word_key
from app.core.search_index import build_entry_search_blob
from app.storage.workbook_revision import WorkbookRevision


@dataclass(frozen=True)
class CellState:
    header: Any
    key: str
    value: Any
    data_type: str
    font: Any
    fill: Any
    border: Any
    alignment: Any
    number_format: str
    protection: Any
    hyperlink: Any
    comment: Any

    @classmethod
    def capture(cls, cell: Cell, header: Any, key: str) -> "CellState":
        return cls(
            header=header,
            key=key,
            value=cell.value,
            data_type=cell.data_type,
            font=copy(cell.font),
            fill=copy(cell.fill),
            border=copy(cell.border),
            alignment=copy(cell.alignment),
            number_format=cell.number_format,
            protection=copy(cell.protection),
            hyperlink=copy(cell.hyperlink),
            comment=copy(cell.comment),
        )

    def apply(self, cell: Cell) -> None:
        cell.value = self.value
        cell.data_type = self.data_type
        cell.font = copy(self.font)
        cell.fill = copy(self.fill)
        cell.border = copy(self.border)
        cell.alignment = copy(self.alignment)
        cell.number_format = self.number_format
        cell.protection = copy(self.protection)
        if self.hyperlink is None:
            cell.hyperlink = None
        else:
            hyperlink = copy(self.hyperlink)
            hyperlink.ref = cell.coordinate
            cell.hyperlink = hyperlink
        cell.comment = copy(self.comment)


@dataclass(frozen=True)
class SnapshotCell:
    header: Any
    key: str
    value: Any
    data_type: str


@dataclass(frozen=True)
class RowSnapshot:
    ref: EntryRef
    original_row_number: int
    entry_json: str
    cells: tuple[CellState, ...]
    height: float | None = None
    hidden: bool = False
    outline_level: int = 0

    @property
    def entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.entry_json)


@dataclass(frozen=True)
class SnapshotRow:
    ref: EntryRef
    entry_json: str
    cells: tuple[SnapshotCell, ...]
    search_blob: str = field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.search_blob:
            object.__setattr__(self, "search_blob", build_entry_search_blob(self.entry))

    @property
    def entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.entry_json)


@dataclass(frozen=True)
class WorkbookSnapshot:
    path: Path
    revision: WorkbookRevision
    sheet_name: str
    headers: tuple[Any, ...]
    columns: tuple[str, ...]
    rows: tuple[SnapshotRow, ...]
    _ref_index: Mapping[EntryRef, SnapshotRow] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _key_index: Mapping[tuple[str, str], SnapshotRow] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _language_rows: Mapping[str, tuple[SnapshotRow, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        ref_index: dict[EntryRef, SnapshotRow] = {}
        key_index: dict[tuple[str, str], SnapshotRow] = {}
        language_rows: dict[str, list[SnapshotRow]] = {}
        for row in self.rows:
            ref_index[row.ref] = row
            key_index.setdefault((row.ref.language, row.ref.word_key), row)
            language_rows.setdefault(row.ref.language, []).append(row)
        object.__setattr__(self, "_ref_index", MappingProxyType(ref_index))
        object.__setattr__(self, "_key_index", MappingProxyType(key_index))
        object.__setattr__(
            self,
            "_language_rows",
            MappingProxyType({language: tuple(rows) for language, rows in language_rows.items()}),
        )

    @property
    def entries(self) -> tuple[VocabularyEntry, ...]:
        return tuple(row.entry for row in self.rows)

    def find_ref(self, ref: EntryRef) -> SnapshotRow | None:
        return self._ref_index.get(ref)

    def find_key(self, language: str, word_key: str) -> SnapshotRow | None:
        return self._key_index.get((language, word_key))

    def rows_for(self, language: str) -> tuple[SnapshotRow, ...]:
        return self._language_rows.get(language, ())


def row_identity(values: tuple[Any, ...], data_types: tuple[str, ...]) -> str:
    payload = json.dumps(
        {
            "values": [_stable_value(value) for value in values],
            "types": list(data_types),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def entry_ref(
    entry: VocabularyEntry,
    row_number: int,
    values: tuple[Any, ...],
    data_types: tuple[str, ...],
) -> EntryRef:
    return EntryRef(
        language=entry.language,
        word_key=normalize_word_key(entry.word, entry.language),
        row_number=row_number,
        identity=row_identity(values, data_types),
    )


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return {"isoformat": value.isoformat()}
        except (TypeError, ValueError):
            pass
    return {"type": type(value).__name__, "repr": repr(value)}
