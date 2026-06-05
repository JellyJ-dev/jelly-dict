from __future__ import annotations

import json
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.utils import utc_now_str

Language = Literal["en", "ja"]
SourceProvider = Literal["naver_en", "naver_ja", "manual", "naver_api", "unknown"]


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Example:
    source_text: str = ""
    source_text_plain: str = ""
    translation_ko: str | None = None
    order: int = 0


@dataclass
class SubSense:
    label: str = ""
    gloss: str = ""
    examples: list[Example] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)


@dataclass
class Sense:
    number: int = 0
    gloss: str = ""
    sub_senses: list[SubSense] = field(default_factory=list)


@dataclass
class MeaningGroup:
    pos: str = ""
    senses: list[Sense] = field(default_factory=list)


@dataclass
class VocabularyEntry:
    language: Language = "en"
    word: str = ""
    reading: str | None = None
    pronunciation_audio_url: str | None = None
    part_of_speech: list[str] = field(default_factory=list)
    meaning_groups: list[MeaningGroup] = field(default_factory=list)
    meanings_summary: str = ""
    examples_flat: list[Example] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    memo: str = ""
    source_url: str | None = None
    source_provider: SourceProvider = "unknown"
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=utc_now_str)
    updated_at: str = field(default_factory=utc_now_str)

    def word_key(self) -> str:
        return normalize_word_key(self.word, self.language)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VocabularyEntry:
        meaning_groups = [
            MeaningGroup(
                pos=mg.get("pos", ""),
                senses=[
                    Sense(
                        number=s.get("number", 0),
                        gloss=s.get("gloss", ""),
                        sub_senses=[
                            SubSense(
                                label=ss.get("label", ""),
                                gloss=ss.get("gloss", ""),
                                examples=[Example(**ex) for ex in ss.get("examples", [])],
                                synonyms=list(ss.get("synonyms", [])),
                                antonyms=list(ss.get("antonyms", [])),
                            )
                            for ss in s.get("sub_senses", [])
                        ],
                    )
                    for s in mg.get("senses", [])
                ],
            )
            for mg in data.get("meaning_groups", [])
        ]
        examples_flat = [Example(**ex) for ex in data.get("examples_flat", [])]
        return cls(
            language=data.get("language", "en"),
            word=data.get("word", ""),
            reading=data.get("reading"),
            pronunciation_audio_url=data.get("pronunciation_audio_url"),
            part_of_speech=list(data.get("part_of_speech", [])),
            meaning_groups=meaning_groups,
            meanings_summary=data.get("meanings_summary", ""),
            examples_flat=examples_flat,
            synonyms=list(data.get("synonyms", [])),
            antonyms=list(data.get("antonyms", [])),
            tags=list(data.get("tags", [])),
            memo=data.get("memo", ""),
            source_url=data.get("source_url"),
            source_provider=data.get("source_provider", "unknown"),
            id=data.get("id", _new_id()),
            created_at=data.get("created_at", utc_now_str()),
            updated_at=data.get("updated_at", utc_now_str()),
        )

    @classmethod
    def from_json(cls, payload: str) -> VocabularyEntry:
        return cls.from_dict(json.loads(payload))

    def touch(self) -> None:
        self.updated_at = utc_now_str()


def normalize_word_key(word: str, language: Language) -> str:
    """Canonical key for duplicate detection and cache lookup."""
    text = (word or "").strip()
    if language == "en":
        return text.lower()
    return unicodedata.normalize("NFKC", text)


from app.core.meaning_display import (  # noqa: E402
    build_meanings_summary,
    collect_examples_flat,
    first_meaning_hint,
    sanitize_meaning_gloss,
    wordbook_meaning_hint,
)
