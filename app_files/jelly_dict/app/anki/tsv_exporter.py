"""TSV export for Anki import."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.anki.temp_utils import new_temp_path
from app.anki.render import FIELD_ORDER, fields_for_entry
from app.core.errors import ExportError
from app.core.models import VocabularyEntry


def export_tsv(path: Path, entries: Iterable[VocabularyEntry]) -> int:
    """Write an Anki-compatible TSV. Returns row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    rows.append("#separator:tab")
    rows.append("#html:true")
    rows.append("#columns:" + ",".join(list(FIELD_ORDER) + ["Tags"]))

    count = 0
    for entry in entries:
        fields = fields_for_entry(entry)
        cells = [_clean(fields.get(name, "")) for name in FIELD_ORDER]
        cells.append(" ".join(_clean_tag(t) for t in entry.tags))
        rows.append("\t".join(cells))
        count += 1

    try:
        temp_path = new_temp_path(path)
        try:
            with temp_path.open("w", encoding="utf-8-sig", newline="\n") as f:
                f.write("\n".join(rows))
            temp_path.replace(path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    except OSError as exc:
        raise ExportError(str(exc)) from exc
    return count


def _clean(value: str) -> str:
    return (value or "").replace("\t", " ").replace("\r", " ").replace("\n", "<br>")


def _clean_tag(tag: str) -> str:
    return tag.strip().replace(" ", "_")
