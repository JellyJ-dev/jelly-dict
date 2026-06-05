"""Cell-level serialization between VocabularyEntry and Excel rows.

Pure conversion helpers + style constants. No IO, no openpyxl Workbook
manipulation — that lives in `excel_writer.py` and `excel_reader.py`.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Iterable

from openpyxl.styles import Font, PatternFill

from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
)

SHEET_NAME = "Vocabulary"

COLUMN_LABELS: dict[str, str] = {
    "language": "Language",
    "word": "Word",
    "reading": "Reading/Pronunciation",
    "part_of_speech": "Part of Speech",
    "meanings_summary": "Meanings",
    "meanings_detail": "Meanings Detail",
    "examples": "Examples",
    "example_translations": "Example Translations",
    "synonyms": "Synonyms",
    "antonyms": "Antonyms",
    "tags": "Tags",
    "memo": "Memo",
    "source_url": "Source URL",
    "created_at": "Created At",
    "updated_at": "Updated At",
}

COLUMN_WIDTHS: dict[str, int] = {
    "language": 8,
    "word": 18,
    "reading": 20,
    "part_of_speech": 14,
    "meanings_summary": 40,
    "meanings_detail": 50,
    "examples": 50,
    "example_translations": 40,
    "synonyms": 24,
    "antonyms": 24,
    "tags": 18,
    "memo": 30,
    "source_url": 30,
    "created_at": 22,
    "updated_at": 22,
}

HEADER_FILL = PatternFill(start_color="FF22272E", end_color="FF22272E", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFFFF")


def label_to_key(label) -> str:
    """Map an Excel header cell value back to the canonical field key."""
    if not isinstance(label, str):
        return ""
    for key, expected in COLUMN_LABELS.items():
        if expected == label:
            return key
    return label.lower().replace(" ", "_").replace("/", "_")


def render_cell(entry: VocabularyEntry, key: str) -> str:
    if key == "language":
        return entry.language
    if key == "word":
        return entry.word
    if key == "reading":
        return entry.reading or ""
    if key == "part_of_speech":
        return ", ".join(entry.part_of_speech)
    if key == "meanings_summary":
        return entry.meanings_summary or build_meanings_summary(entry)
    if key == "meanings_detail":
        return render_detail(entry.meaning_groups)
    if key == "examples":
        return "\n".join(
            iter_example_plain(entry.examples_flat or _flatten_examples(entry))
        )
    if key == "example_translations":
        return "\n".join(
            iter_example_translation(entry.examples_flat or _flatten_examples(entry))
        )
    if key == "synonyms":
        return ", ".join(entry.synonyms)
    if key == "antonyms":
        return ", ".join(entry.antonyms)
    if key == "tags":
        return ", ".join(entry.tags)
    if key == "memo":
        return entry.memo
    if key == "source_url":
        return entry.source_url or ""
    if key == "created_at":
        return entry.created_at
    if key == "updated_at":
        return entry.updated_at
    return ""


def _flatten_examples(entry: VocabularyEntry) -> list[Example]:
    return collect_examples_flat(entry)


def iter_example_plain(examples: Iterable[Example]) -> list[str]:
    return [ex.source_text_plain for ex in examples if ex.source_text_plain]


def iter_example_translation(examples: Iterable[Example]) -> list[str]:
    return [ex.translation_ko or "" for ex in examples]


def render_detail(groups: list[MeaningGroup]) -> str:
    """Plain-text rendering of the nested meaning structure for Excel."""
    lines: list[str] = []
    for group in groups:
        if group.pos:
            lines.append(group.pos)
        for sense in group.senses:
            head = f"{sense.number}." if sense.number else "-"
            gloss = sense.gloss or ""
            lines.append(f"  {head} {gloss}".rstrip())
            for sub in sense.sub_senses:
                tag = f"{sub.label}." if sub.label else "-"
                lines.append(f"    {tag} {sub.gloss}".rstrip())
                if sub.synonyms:
                    lines.append(f"      = {', '.join(sub.synonyms)}")
    return "\n".join(lines)


def row_to_entry(keys: list[str], row: tuple) -> VocabularyEntry:
    """Reconstruct a VocabularyEntry from an Excel row.

    Populates examples_flat from the `examples` / `example_translations`
    columns so the entry detail dialog has something to render even
    when the SQLite cache is empty (e.g., on a fresh install or after
    `캐시 비우기`). meaning_groups stay empty — the cell text isn't a
    machine-friendly format and the detail dialog already falls back to
    `meanings_summary` line-splits when groups are missing.
    """
    data: dict[str, str] = {}
    for key, value in zip(keys, row):
        if isinstance(value, str):
            data[key] = value
        elif value is None:
            data[key] = ""
        else:
            data[key] = str(value)

    return row_data_to_entry(data)


def row_data_to_entry(
    data: dict,
    *,
    parse_meanings_detail: bool = False,
    preserve_blank_translations: bool = False,
) -> VocabularyEntry:
    word = str(data.get("word", "")).strip()
    language = str(data.get("language", "en")).strip() or "en"
    sources = [s for s in str(data.get("examples", "") or "").split("\n") if s.strip()]
    translations = str(data.get("example_translations", "") or "").split("\n")
    examples_flat: list[Example] = []
    for idx, src in enumerate(sources):
        translation = translations[idx] if idx < len(translations) else None
        if translation is not None and not preserve_blank_translations:
            translation = translation.strip() or None
        examples_flat.append(
            Example(
                source_text=src,
                source_text_plain=src,
                translation_ko=translation,
                order=idx,
            )
        )

    pos_list = _split_csv(data.get("part_of_speech", ""))
    summary = str(data.get("meanings_summary", "") or "")
    meaning_groups: list[MeaningGroup] = []
    if parse_meanings_detail:
        detail = str(data.get("meanings_detail", "") or "")
        meaning_groups = parse_meanings_detail_cell(detail)
        if meaning_groups:
            if examples_flat:
                replace_nested_examples(meaning_groups, examples_flat)
        elif pos_list and summary:
            meaning_groups = [
                MeaningGroup(
                    pos=pos_list[0],
                    senses=[
                        Sense(
                            number=1,
                            gloss=summary,
                            sub_senses=[SubSense(examples=examples_flat)],
                        )
                    ],
                )
            ]

    return VocabularyEntry(
        language=language,  # type: ignore[arg-type]
        word=word,
        reading=str(data.get("reading", "") or "") or None,
        part_of_speech=pos_list,
        meaning_groups=meaning_groups,
        meanings_summary=summary,
        examples_flat=examples_flat,
        memo=str(data.get("memo", "") or ""),
        synonyms=_split_csv(data.get("synonyms", "")),
        antonyms=_split_csv(data.get("antonyms", "")),
        tags=_split_csv(data.get("tags", "")),
        source_url=str(data.get("source_url", "") or "") or None,
        source_provider="unknown",
        created_at=str(data.get("created_at", "") or ""),
        updated_at=str(data.get("updated_at", "") or ""),
    )


def _split_csv(value) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def parse_meanings_detail_cell(value: str) -> list[MeaningGroup]:
    """Parse the plain-text detail format written to Excel back into groups."""
    groups: list[MeaningGroup] = []
    current_group: MeaningGroup | None = None
    current_sense: Sense | None = None
    current_sub: SubSense | None = None

    for raw_line in (value or "").splitlines():
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        text = raw_line.strip()

        if indent == 0:
            current_group = MeaningGroup(pos=text, senses=[])
            groups.append(current_group)
            current_sense = None
            current_sub = None
            continue

        if current_group is None:
            current_group = MeaningGroup(pos="", senses=[])
            groups.append(current_group)

        if text.startswith("="):
            if current_sub is not None:
                current_sub.synonyms.extend(_split_csv(text[1:]))
            continue

        if indent <= 2:
            number, gloss = _parse_numbered_detail_line(text)
            current_sense = Sense(number=number, gloss=gloss, sub_senses=[])
            current_group.senses.append(current_sense)
            current_sub = None
            continue

        label, gloss = _parse_labeled_detail_line(text)
        current_sub = SubSense(label=label, gloss=gloss)
        if current_sense is None:
            current_sense = Sense(number=0, gloss="", sub_senses=[])
            current_group.senses.append(current_sense)
        current_sense.sub_senses.append(current_sub)

    return [group for group in groups if group.pos or group.senses]


def _parse_numbered_detail_line(text: str) -> tuple[int, str]:
    match = re.match(r"(?:(\d+)\.|[-*])\s*(.*)", text)
    if not match:
        return 0, text
    number = int(match.group(1) or 0)
    return number, match.group(2).strip()


def _parse_labeled_detail_line(text: str) -> tuple[str, str]:
    match = re.match(r"(?:(?P<label>[^.\s]+)\.|[-*])\s*(?P<gloss>.*)", text)
    if not match:
        return "", text
    return (match.group("label") or "").strip(), match.group("gloss").strip()


def replace_nested_examples(
    groups: list[MeaningGroup],
    examples: list[Example],
) -> None:
    attached = False
    for group in groups:
        for sense in group.senses:
            for sub in sense.sub_senses:
                if not attached:
                    sub.examples = deepcopy(examples)
                    attached = True
                else:
                    sub.examples = []
    if attached or not groups or not groups[0].senses:
        return
    groups[0].senses[0].sub_senses.append(SubSense(examples=deepcopy(examples)))
