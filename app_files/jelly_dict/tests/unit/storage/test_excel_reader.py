from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.storage.excel_reader import find_existing, list_entries
from app.storage.excel_serializer import COLUMN_LABELS, SHEET_NAME


def _write_reader_workbook(path: Path) -> None:
    wb = Workbook()
    try:
        ws = wb.active
        ws.title = SHEET_NAME
        ws.append([
            COLUMN_LABELS["language"],
            COLUMN_LABELS["word"],
            COLUMN_LABELS["meanings_summary"],
        ])
        ws.append(["en", "Apple", "사과"])
        ws.append([None, None, None])
        wb.save(path)
    finally:
        wb.close()


def test_list_entries_skips_blank_rows(tmp_path: Path):
    path = tmp_path / "vocab.xlsx"
    _write_reader_workbook(path)

    entries = list_entries(path)

    assert len(entries) == 1
    assert entries[0].word == "Apple"


def test_find_existing_matches_normalized_key(tmp_path: Path):
    path = tmp_path / "vocab.xlsx"
    _write_reader_workbook(path)

    assert find_existing(path, "en", "apple").word == "Apple"
    assert find_existing(path, "ja", "apple") is None


def test_reader_missing_or_invalid_workbook_returns_empty(tmp_path: Path):
    assert list_entries(tmp_path / "missing.xlsx") == []
    assert find_existing(tmp_path / "missing.xlsx", "en", "apple") is None
