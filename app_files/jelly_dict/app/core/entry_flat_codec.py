from __future__ import annotations

import re

from app.core.meaning_display import replace_nested_examples
from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
)


def row_data_to_entry(
    data: dict,
    *,
    parse_meanings_detail: bool = False,
    preserve_blank_translations: bool = False,
) -> VocabularyEntry:
    word = str(data.get("word", "")).strip()
    language = str(data.get("language", "en")).strip() or "en"
    sources = [
        source for source in str(data.get("examples", "") or "").split("\n") if source.strip()
    ]
    translations = str(data.get("example_translations", "") or "").split("\n")
    examples_flat: list[Example] = []
    for index, source in enumerate(sources):
        translation = translations[index] if index < len(translations) else None
        if translation is not None and not preserve_blank_translations:
            translation = translation.strip() or None
        examples_flat.append(
            Example(
                source_text=source,
                source_text_plain=source,
                translation_ko=translation,
                order=index,
            )
        )

    part_of_speech = _split_csv(data.get("part_of_speech", ""))
    summary = str(data.get("meanings_summary", "") or "")
    meaning_groups: list[MeaningGroup] = []
    if parse_meanings_detail:
        detail = str(data.get("meanings_detail", "") or "")
        meaning_groups = parse_meanings_detail_cell(detail)
        if meaning_groups and examples_flat:
            replace_nested_examples(meaning_groups, examples_flat)
        elif not meaning_groups and part_of_speech and summary:
            meaning_groups = [
                MeaningGroup(
                    pos=part_of_speech[0],
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
        part_of_speech=part_of_speech,
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


def parse_meanings_detail_cell(value: str) -> list[MeaningGroup]:
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


def _split_csv(value) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _parse_numbered_detail_line(text: str) -> tuple[int, str]:
    match = re.match(r"(?:(\d+)\.|[-*])\s*(.*)", text)
    if not match:
        return 0, text
    return int(match.group(1) or 0), match.group(2).strip()


def _parse_labeled_detail_line(text: str) -> tuple[str, str]:
    match = re.match(r"(?:(?P<label>[^.\s]+)\.|[-*])\s*(?P<gloss>.*)", text)
    if not match:
        return "", text
    return (match.group("label") or "").strip(), match.group("gloss").strip()
