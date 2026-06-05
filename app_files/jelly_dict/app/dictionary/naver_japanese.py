"""Naver Japanese dictionary parser.

The Japanese page is structurally simpler than the English one:

  .row (one entry)
    .origin
      a.link              ← reading (kana)
      span.text._kanji    ← kanji form
      .unit_listen        ← audio button
    p.word_class          ← POS in Korean ("명사", "동사" ...)
    ul.mean_list.multi
      li.mean_item
        span.num "1."
        p.mean             ← Korean meaning text, may contain
          span.related_word ← synonym/related kana

Examples live in a separate section after the entry rows:

  .component_example
    .row
      .origin .text       (with <ruby> for furigana)
      .translate p.text   (Korean translation)

Selectors are kept as module-level constants per dev.md §16 rule 9.
"""
from __future__ import annotations

import logging
import re

from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
)
from app.dictionary.parser_utils import (
    aggregate_relations,
    extract_number,
    first,
    make_soup,
    ruby_html,
    strip_furigana,
    text_or_empty,
)

LOOKUP_URL = "https://ja.dict.naver.com/#/search?query={query}"

# --- Selectors (confirmed against ja.dict.naver.com 2026-05) ----------
SEL_ENTRY_ROW = ".search_result .row, .row"  # matches first dictionary entry block
SEL_ORIGIN = ".origin"
SEL_READING = ".origin > a.link"
SEL_KANJI = ".origin .text._kanji"
SEL_AUDIO = ".origin .unit_listen .btn_listen"
SEL_POS = "p.word_class"
SEL_MEAN_LIST = "ul.mean_list"
SEL_MEAN_ITEM = "li.mean_item"
SEL_MEAN_NUM = "span.num"
SEL_MEAN_TEXT = "p.mean"
SEL_RELATED_WORD = "span.related_word"
SEL_EXAMPLE_SECTION = ".component_example"
SEL_EXAMPLE_ROW = ".row"
SEL_EXAMPLE_SOURCE = ".origin .text"
SEL_EXAMPLE_TRANSLATION = ".translate .text, .translate p"
# ----------------------------------------------------------------------

WAIT_SELECTOR = (
    ".search_result .row p.word_class, "
    ".search_result .row .mean_list, "
    ".row .mean_list, "
    ".component_example"
)

log = logging.getLogger(__name__)


def lookup_url(word: str) -> str:
    from urllib.parse import quote

    return LOOKUP_URL.format(query=quote(word))


def parse(html: str, *, word: str, source_url: str) -> VocabularyEntry | None:
    entry, _ = parse_with_canonical(html, word=word, source_url=source_url)
    return entry


def parse_with_canonical(
    html: str, *, word: str, source_url: str
) -> tuple[VocabularyEntry | None, str]:
    """Same as parse() but also returns the canonical headword from the
    page, so the caller can decide whether to ask 'did you mean ...?'."""
    soup = make_soup(html)
    entry_row = _find_primary_row(soup)
    if entry_row is None:
        return None, ""

    canonical_head, reading = _parse_head(entry_row, word)
    # Save the typed variant when Naver publishes multiple equivalent
    # forms such as 蘇る·甦る; otherwise keep the dictionary lemma.
    headword = _resolve_headword(word, canonical_head)
    pos = text_or_empty(first(entry_row, SEL_POS))
    senses = _parse_senses(entry_row)
    if not senses and not reading:
        return None, canonical_head

    meaning_groups = [MeaningGroup(pos=pos, senses=senses)] if (pos or senses) else []
    examples = _parse_examples(soup)
    if examples and meaning_groups:
        # Attach all examples under the first sense's first sub-sense.
        first_sense = meaning_groups[0].senses[0] if meaning_groups[0].senses else None
        if first_sense is None:
            first_sense = Sense(number=1, gloss="", sub_senses=[])
            meaning_groups[0].senses.append(first_sense)
        if not first_sense.sub_senses:
            first_sense.sub_senses.append(SubSense(label="", gloss=""))
        first_sense.sub_senses[0].examples = examples

    entry = VocabularyEntry(
        language="ja",
        word=headword,
        reading=reading or None,
        pronunciation_audio_url=None,
        part_of_speech=[pos] if pos else [],
        meaning_groups=meaning_groups,
        synonyms=aggregate_relations(meaning_groups, "synonyms"),
        antonyms=[],
        source_url=source_url,
        source_provider="naver_ja",
    )
    entry.examples_flat = collect_examples_flat(entry)
    entry.meanings_summary = build_meanings_summary(entry)
    return entry, canonical_head


def _find_primary_row(soup):
    """Return the first .row that contains a .word_class — that's a real
    dictionary entry (other .row instances are pagination/ads/UI)."""
    for row in soup.select(".row"):
        if row.select_one(SEL_POS) and row.select_one(SEL_MEAN_LIST):
            return row
    return None


def _parse_head(entry_row, fallback: str) -> tuple[str, str]:
    """Return (headword, reading). Headword is kanji if present, else reading."""
    reading_node = first(entry_row, SEL_READING)
    reading = _normalize_kana(reading_node.get_text(" ", strip=True) if reading_node else "")
    kanji_node = first(entry_row, SEL_KANJI)
    kanji = _strip_brackets(text_or_empty(kanji_node))
    headword = kanji or reading or fallback
    return headword, reading


def _strip_brackets(text: str) -> str:
    """'[ 月 日 ]' -> '月日'  (Naver inserts spaces between every char)"""
    text = (text or "").strip()
    text = re.sub(r"^[\[\(]\s*", "", text)
    text = re.sub(r"\s*[\]\)]$", "", text)
    return re.sub(r"\s+", "", text)


def headword_variants(canonical: str) -> list[str]:
    """Split a headword like '蘇る·甦る' into ['蘇る', '甦る']."""
    if not canonical:
        return []
    parts = re.split(r"[·・/\\]", canonical)
    return [p.strip() for p in parts if p.strip()]


def _resolve_headword(typed: str, canonical: str) -> str:
    """Return the form to actually save.

    Prefer the user-typed word when it is one of the published variants;
    otherwise fall back to the canonical form so the entry is at least
    consistent with what the dictionary returned.
    """
    typed_norm = (typed or "").strip()
    if not typed_norm:
        return canonical
    if not canonical:
        return typed_norm
    variants = headword_variants(canonical)
    if typed_norm in variants or typed_norm == canonical:
        return typed_norm
    return canonical


def did_you_mean(typed: str, canonical: str) -> str | None:
    """Return a suggestion when the dictionary's headword is unrelated
    to what the user typed (likely a typo or wrong query)."""
    if not canonical or not typed or typed == canonical:
        return None
    variants = headword_variants(canonical)
    if typed in variants:
        return None
    # If the typed string is contained in any variant, treat it as
    # equivalent (no suggestion needed).
    for v in variants:
        if typed in v or v in typed:
            return None
    return canonical


def _normalize_kana(text: str) -> str:
    """Naver wraps each kana in a span and joins with spaces; collapse them."""
    return re.sub(r"\s+", "", (text or "").strip())


def _parse_senses(entry_row) -> list[Sense]:
    senses: list[Sense] = []
    mean_list = first(entry_row, SEL_MEAN_LIST)
    if mean_list is None:
        return senses
    for idx, item in enumerate(mean_list.select(SEL_MEAN_ITEM), start=1):
        number = extract_number(first(item, SEL_MEAN_NUM)) or idx
        mean_node = first(item, SEL_MEAN_TEXT)
        if mean_node is None:
            continue
        # Pull related_word out before reading the gloss text.
        related = [
            _normalize_kana(rel.get_text(" ", strip=True))
            for rel in mean_node.select(SEL_RELATED_WORD)
        ]
        for rel in mean_node.select(SEL_RELATED_WORD):
            rel.decompose()
        gloss = text_or_empty(mean_node)
        gloss = re.sub(r"\(=\s*\)$", "", gloss).strip()  # leftover "(= )" if related was inline
        sub_senses: list[SubSense] = []
        if related:
            sub_senses.append(SubSense(label="", gloss="", synonyms=related))
        senses.append(Sense(number=number, gloss=gloss, sub_senses=sub_senses))
    return senses


def _parse_examples(soup) -> list[Example]:
    section = first(soup, SEL_EXAMPLE_SECTION)
    if section is None:
        return []
    items: list[Example] = []
    for idx, row in enumerate(section.select(SEL_EXAMPLE_ROW)):
        src_node = first(row, SEL_EXAMPLE_SOURCE)
        trans_node = first(row, SEL_EXAMPLE_TRANSLATION)
        if src_node is None and trans_node is None:
            continue
        src_html = ruby_html(src_node)
        src_plain = strip_furigana(src_node)
        trans = text_or_empty(trans_node)
        if not src_plain and not trans:
            continue
        items.append(
            Example(
                source_text=src_html or src_plain,
                source_text_plain=src_plain,
                translation_ko=trans or None,
                order=idx,
            )
        )
    return items
