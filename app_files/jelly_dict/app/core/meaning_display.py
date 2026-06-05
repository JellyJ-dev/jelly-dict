from __future__ import annotations

import re

_EN_HANGUL_RE = re.compile(r"[가-힣]")
_EN_REFERENCE_RE = re.compile(r"\s*(?:\((?:=|→|->)\s*[^)]*\)|(?:=|→|->)\s*\S+)\s*")
_EN_GLOSS_STOPWORDS = {
    "구어",
    "드물게",
    "문어",
    "미국",
    "방언",
    "비격식",
    "속어",
    "영국",
    "용어",
    "전문",
    "주로",
    "특히",
}


def build_meanings_summary(entry: "VocabularyEntry") -> str:
    if not entry.meaning_groups:
        return ""

    primary = entry.meaning_groups[0]
    pos_label = primary.pos.strip()
    parts: list[str] = []
    for sense in primary.senses:
        gloss = (sense.gloss or "").strip()
        if not gloss and sense.sub_senses:
            gloss = (sense.sub_senses[0].gloss or "").strip()
        gloss = sanitize_meaning_gloss(gloss, entry.language)
        if not gloss:
            continue
        number = len(parts) + 1
        parts.append(f"{number}. {_short_gloss(gloss)}")

    body = " ".join(parts)
    if not body:
        return ""
    if pos_label:
        return f"[{pos_label}] {body}"
    return body


def first_meaning_hint(entry: "VocabularyEntry", limit: int = 40) -> str:
    for group in entry.meaning_groups:
        for sense in group.senses:
            if sense.gloss:
                gloss = sanitize_meaning_gloss(sense.gloss, entry.language)
                if gloss:
                    return _trim_hint(gloss, limit=limit)
            for sub in sense.sub_senses:
                if sub.gloss:
                    gloss = sanitize_meaning_gloss(sub.gloss, entry.language)
                    if gloss:
                        return _trim_hint(gloss, limit=limit)
    if entry.meanings_summary:
        stripped = re.sub(r"^\[[^\]]+\]\s*", "", entry.meanings_summary)
        parts = re.split(r"\s*\d+\s*\.\s*", stripped)
        for part in parts:
            gloss = sanitize_meaning_gloss(part, entry.language)
            if gloss:
                return _trim_hint(gloss, limit=limit)
    return ""


def wordbook_meaning_hint(entry: "VocabularyEntry", limit: int = 160) -> str:
    parts: list[str] = []
    if entry.meaning_groups:
        for sense in entry.meaning_groups[0].senses:
            gloss = (sense.gloss or "").strip()
            if not gloss and sense.sub_senses:
                gloss = (sense.sub_senses[0].gloss or "").strip()
            gloss = sanitize_meaning_gloss(gloss, entry.language)
            if not gloss:
                continue
            number = len(parts) + 1
            parts.append(f"{number}.{_short_gloss(gloss)}")
    if len(parts) > 1:
        return _trim_hint(" ".join(parts), limit=limit)
    if len(parts) == 1:
        return _trim_hint(parts[0].split(".", 1)[1], limit=limit)
    return first_meaning_hint(entry, limit=limit)


def sanitize_meaning_gloss(text: str, language: "Language" = "en") -> str:
    gloss = re.sub(r"\s+", " ", (text or "")).strip()
    if not gloss:
        return ""
    if language != "en":
        return gloss
    gloss = _EN_REFERENCE_RE.sub(" ", gloss)
    gloss = re.sub(r"\s+", " ", gloss).strip(" .;")
    if not _EN_HANGUL_RE.search(gloss):
        return ""
    chunks = re.findall(r"[가-힣]+", gloss)
    meaningful = [chunk for chunk in chunks if chunk not in _EN_GLOSS_STOPWORDS]
    if not meaningful:
        return ""
    return gloss


def collect_examples_flat(entry: "VocabularyEntry") -> list["Example"]:
    from app.core.models import Example

    flat: list[Example] = []
    order = 0
    for mg in entry.meaning_groups:
        for sense in mg.senses:
            for sub in sense.sub_senses:
                for ex in sub.examples:
                    flat.append(
                        Example(
                            source_text=ex.source_text,
                            source_text_plain=ex.source_text_plain,
                            translation_ko=ex.translation_ko,
                            order=order,
                        )
                    )
                    order += 1
    return flat


def _short_gloss(text: str) -> str:
    for sep in (";", ",", "/"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text.strip().rstrip(".")


def _trim_hint(text: str, limit: int = 40) -> str:
    text = (text or "").strip().rstrip(".")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
