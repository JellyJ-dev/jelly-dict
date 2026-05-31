from __future__ import annotations

from openpyxl import load_workbook

from app.core.models import Example, MeaningGroup, Sense, SubSense, VocabularyEntry
from app.services.export_service import ExportService, entry_from_export_row
from app.storage.cache_store import CacheStore
from app.storage.excel_writer import append_entry
from app.storage.excel_serializer import SHEET_NAME
from app.storage.settings_store import EXCEL_COLUMN_KEYS_DEFAULT, Settings


def _row(**overrides):
    data = {
        "language": "en",
        "word": "performance",
        "reading": "",
        "part_of_speech": "Noun",
        "meanings_summary": "1.공연 2.실적",
        "examples": "",
        "example_translations": "",
        "synonyms": "",
        "antonyms": "",
        "tags": "school",
        "memo": "edited",
        "source_url": "https://example.test",
        "created_at": "",
        "updated_at": "",
    }
    data.update(overrides)
    return data


def test_export_row_prefers_excel_summary_over_stale_cache() -> None:
    cached = VocabularyEntry(
        language="en",
        word="performance",
        part_of_speech=["Noun"],
        meanings_summary="old cache",
        meaning_groups=[MeaningGroup(pos="Noun", senses=[Sense(number=1, gloss="old cache")])],
        memo="cache memo",
        tags=["cache-tag"],
    )

    entry = entry_from_export_row(_row(), cached)

    assert entry.meanings_summary == "1.공연 2.실적"
    assert entry.meaning_groups[0].senses[0].gloss == "1.공연 2.실적"
    assert entry.memo == "edited"
    assert entry.tags == ["school"]


def test_export_row_reuses_matching_cache_structure_without_mutating_cache() -> None:
    cached = VocabularyEntry(
        language="en",
        word="performance",
        part_of_speech=["Noun"],
        meanings_summary="1.공연 2.실적",
        meaning_groups=[
            MeaningGroup(
                pos="Noun",
                senses=[
                    Sense(number=1, gloss="공연"),
                    Sense(number=2, gloss="실적"),
                ],
            )
        ],
    )

    entry = entry_from_export_row(_row(), cached)
    entry.meaning_groups[0].senses[0].gloss = "changed"

    assert len(entry.meaning_groups[0].senses) == 2
    assert cached.meaning_groups[0].senses[0].gloss == "공연"


def test_export_row_keeps_excel_examples_ahead_of_cache_examples() -> None:
    cached = VocabularyEntry(
        language="en",
        word="performance",
        part_of_speech=["Noun"],
        meanings_summary="1.공연 2.실적",
        meaning_groups=[
            MeaningGroup(
                pos="Noun",
                senses=[
                    Sense(
                        number=1,
                        gloss="공연",
                        sub_senses=[
                            SubSense(
                                examples=[
                                    Example(
                                        source_text="old",
                                        source_text_plain="old",
                                        translation_ko="old ko",
                                    )
                                ]
                            )
                        ],
                    )
                ],
            )
        ],
    )

    entry = entry_from_export_row(
        _row(examples="new example", example_translations="새 예문"),
        cached,
    )

    nested_examples = entry.meaning_groups[0].senses[0].sub_senses[0].examples
    assert entry.examples_flat[0].source_text == "new example"
    assert nested_examples[0].source_text == "new example"
    assert nested_examples[0].translation_ko == "새 예문"


def test_export_row_preserves_blank_translation_lines() -> None:
    entry = entry_from_export_row(
        _row(examples="first\nsecond", example_translations="\n두 번째"),
    )

    assert [ex.translation_ko for ex in entry.examples_flat] == ["", "두 번째"]


def test_collect_entries_filters_requested_language(tmp_path) -> None:
    workbook = tmp_path / "vocab.xlsx"
    append_entry(
        workbook,
        VocabularyEntry(language="en", word="apple"),
        EXCEL_COLUMN_KEYS_DEFAULT,
    )
    append_entry(
        workbook,
        VocabularyEntry(language="ja", word="月日"),
        EXCEL_COLUMN_KEYS_DEFAULT,
    )
    settings = Settings(excel_path_en=str(workbook), excel_path_ja=str(workbook))
    service = ExportService(settings, CacheStore(tmp_path / "cache.db"))

    entries = service._collect_entries("en")

    assert [(entry.language, entry.word) for entry in entries] == [("en", "apple")]


def test_collect_entries_skips_blank_language_rows(tmp_path) -> None:
    workbook = tmp_path / "vocab.xlsx"
    append_entry(
        workbook,
        VocabularyEntry(language="en", word="orphan"),
        EXCEL_COLUMN_KEYS_DEFAULT,
    )
    append_entry(
        workbook,
        VocabularyEntry(language="en", word="apple"),
        EXCEL_COLUMN_KEYS_DEFAULT,
    )
    wb = load_workbook(workbook)
    try:
        wb[SHEET_NAME]["A2"] = ""
        wb.save(workbook)
    finally:
        wb.close()
    settings = Settings(excel_path_en=str(workbook))
    service = ExportService(settings, CacheStore(tmp_path / "cache.db"))

    entries = service._collect_entries("en")

    assert [entry.word for entry in entries] == ["apple"]
