"""Pure presentation model for the entry-detail dialog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.models import (
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
    sanitize_meaning_gloss,
)


@dataclass(frozen=True)
class DetailExample:
    display_text: str
    tts_text: str


@dataclass(frozen=True)
class DetailWordList:
    title: str
    text: str


@dataclass(frozen=True)
class DetailSource:
    url: str
    text: str


@dataclass(frozen=True)
class EntryDetailViewModel:
    title: str
    full_form: str
    reading: str
    first_gloss: str
    meta: str
    meaning_rows: tuple[str, ...]
    examples: tuple[DetailExample, ...]
    word_lists: tuple[DetailWordList, ...]
    memo: str
    source: DetailSource | None

    @classmethod
    def from_entry(cls, entry: VocabularyEntry) -> "EntryDetailViewModel":
        full_form = (entry.word or "").strip()
        title = primary_form(full_form)
        return cls(
            title=title,
            full_form=full_form if full_form != title else "",
            reading=primary_form(entry.reading or ""),
            first_gloss=first_gloss(entry),
            meta=" · ".join([", ".join(entry.part_of_speech)] if entry.part_of_speech else []),
            meaning_rows=meaning_rows(entry),
            examples=tuple(
                DetailExample(
                    display_text=(
                        f"{example.source_text_plain or example.source_text}\n"
                        f"{example.translation_ko}"
                        if example.translation_ko
                        else (example.source_text_plain or example.source_text)
                    ),
                    tts_text=example.source_text_plain or example.source_text,
                )
                for example in (entry.examples_flat or collect_examples_flat(entry))
            ),
            word_lists=tuple(
                section
                for section in (
                    word_list("동의어", entry.synonyms),
                    word_list("반의어", entry.antonyms),
                    word_list("태그", entry.tags),
                )
                if section is not None
            ),
            memo=(entry.memo or "").strip(),
            source=source_presentation(entry),
        )


def meaning_rows(entry: VocabularyEntry) -> tuple[str, ...]:
    rows: list[str] = []
    if entry.meaning_groups:
        visible_index = 0
        for group in entry.meaning_groups:
            for sense in group.senses:
                text = sense.gloss.strip()
                if not text and sense.sub_senses:
                    text = sense.sub_senses[0].gloss.strip()
                text = sanitize_meaning_gloss(text, entry.language)
                if not text:
                    continue
                visible_index += 1
                rows.append(f"{visible_index}. {text}")
        return tuple(rows)

    visible = [
        gloss
        for gloss in (
            sanitize_meaning_gloss(gloss, entry.language)
            for gloss in split_summary_senses(entry.meanings_summary)
        )
        if gloss
    ]
    return tuple(f"{index}. {gloss}" for index, gloss in enumerate(visible, start=1))


def word_list(title: str, words: list[str]) -> DetailWordList | None:
    if not words:
        return None
    visible = words[:20]
    text = ", ".join(visible)
    if len(words) > len(visible):
        text += f" · 외 {len(words) - len(visible)}개"
    return DetailWordList(title, text)


def source_presentation(entry: VocabularyEntry) -> DetailSource | None:
    url = (entry.source_url or "").strip()
    source = source_label(entry.source_provider or "", url)
    if not url and not source:
        return None
    return DetailSource(url=url, text=f"source: {source or display_url(url)}")


def source_label(provider: str, url: str) -> str:
    if provider == "naver_open":
        return "NAVER 오픈사전"
    if provider in {"naver_en", "naver_ja", "naver_api"}:
        return "NAVER"
    if provider == "manual":
        return "Manual"
    domain = urlparse(url).netloc.lower()
    if "naver." in domain:
        return "NAVER"
    return domain.removeprefix("www.")


def display_url(url: str, limit: int = 72) -> str:
    parsed = urlparse(url)
    shown = (parsed.netloc + parsed.path).strip("/") if parsed.netloc else url
    if parsed.query and len(shown) < limit:
        shown = f"{shown}?{parsed.query}"
    if len(shown) <= limit:
        return shown
    head = max(12, (limit - 1) // 2)
    tail = max(12, limit - head - 1)
    return f"{shown[:head]}…{shown[-tail:]}"


def primary_form(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for separator in ("·", "・", "/", "\\"):
        if separator in text:
            return text.split(separator, 1)[0].strip()
    return text


def split_summary_senses(summary: str) -> list[str]:
    if not summary:
        return []
    body = re.sub(r"^\[[^\]]+\]\s*", "", summary).strip()
    if not body:
        return []
    parts = re.split(r"\s*\d+\s*\.\s*", body)
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned or [body]


def first_gloss(entry: VocabularyEntry) -> str:
    for group in entry.meaning_groups:
        for sense in group.senses:
            if sense.gloss:
                gloss = sanitize_meaning_gloss(sense.gloss, entry.language)
                if gloss:
                    return gloss
            for sub_sense in sense.sub_senses:
                if sub_sense.gloss:
                    gloss = sanitize_meaning_gloss(sub_sense.gloss, entry.language)
                    if gloss:
                        return gloss
    summary = entry.meanings_summary or build_meanings_summary(entry)
    if not summary:
        return ""
    senses = [
        gloss
        for gloss in (
            sanitize_meaning_gloss(gloss, entry.language) for gloss in split_summary_senses(summary)
        )
        if gloss
    ]
    return senses[0] if senses else summary


__all__ = [
    "DetailExample",
    "DetailSource",
    "DetailWordList",
    "EntryDetailViewModel",
    "display_url",
    "first_gloss",
    "meaning_rows",
    "primary_form",
    "source_label",
    "split_summary_senses",
]
