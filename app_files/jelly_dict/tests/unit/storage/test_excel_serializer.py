from __future__ import annotations

from app.core.models import Example, MeaningGroup, Sense, SubSense
from app.storage.excel_serializer import (
    COLUMN_LABELS,
    label_to_key,
    parse_meanings_detail_cell,
    render_cell,
    render_detail,
    row_data_to_entry,
)


def test_label_to_key_maps_known_and_legacy_headers():
    assert label_to_key(COLUMN_LABELS["meanings_summary"]) == "meanings_summary"
    assert label_to_key("Example Translations") == "example_translations"
    assert label_to_key(None) == ""


def test_render_cell_uses_flat_examples(sample_entry):
    assert render_cell(sample_entry, "examples") == "I ate an apple."
    assert render_cell(sample_entry, "example_translations") == "나는 사과를 먹었다."
    assert render_cell(sample_entry, "synonyms") == "pome"


def test_meanings_detail_round_trip_preserves_synonyms():
    groups = [
        MeaningGroup(
            pos="Noun",
            senses=[
                Sense(
                    number=1,
                    gloss="사과",
                    sub_senses=[SubSense(label="a", gloss="과일", synonyms=["fruit"])],
                )
            ],
        )
    ]

    parsed = parse_meanings_detail_cell(render_detail(groups))

    assert parsed[0].pos == "Noun"
    assert parsed[0].senses[0].sub_senses[0].synonyms == ["fruit"]


def test_row_data_to_entry_can_preserve_blank_translations():
    entry = row_data_to_entry(
        {
            "language": "en",
            "word": "apple",
            "examples": "one\ntwo",
            "example_translations": "하나\n",
        },
        preserve_blank_translations=True,
    )

    assert [ex.translation_ko for ex in entry.examples_flat] == ["하나", ""]


def test_row_data_to_entry_parses_detail_and_attaches_examples():
    entry = row_data_to_entry(
        {
            "language": "en",
            "word": "apple",
            "part_of_speech": "Noun",
            "meanings_detail": "Noun\n  1. 사과\n    a. 과일",
            "examples": "I ate an apple.",
            "example_translations": "나는 사과를 먹었다.",
        },
        parse_meanings_detail=True,
    )

    example = entry.meaning_groups[0].senses[0].sub_senses[0].examples[0]
    assert isinstance(example, Example)
    assert example.source_text_plain == "I ate an apple."
