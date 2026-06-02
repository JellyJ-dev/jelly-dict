"""Naver English dictionary parser.

The selectors below are best-effort guesses for the current Naver SPA
markup. They are isolated as module-level constants so a single update
re-targets the whole parser when Naver changes the page structure.

Verification of the actual DOM is part of the first manual integration
pass — see dev.md §15 step 9. Until then `parse()` will return None for
unknown structures and the caller falls back to manual entry.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

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
    dedup_preserve_order,
    extract_number,
    first,
    make_soup,
    text_or_empty,
)

LOOKUP_URL = "https://en.dict.naver.com/#/search?query={query}"
ENTRY_URL = "https://en.dict.naver.com/#/entry/enko/{id}"

# --- Selectors (confirmed against en.dict.naver.com 2026-05) ----------
# The Naver SPA renders the entry into the "All meaning" tray
# (#allMeanGroups). The structure is:
#   #allMeanGroups
#     .part_area > .part_speech                       (POS label)
#     ul.mean_list > li.mean_item > ul.mean_list      (wrapper)
#         > li.mean_item                              (the actual sense)
#             > .mean_desc > .num + .cont > .mean
#             > .example .example_item
#                 > p.origin .text  / p.translate .text
#             > .component_relation .row
#                 em.tit  +  .cont .item
SEL_HEADWORD = ".entry_title"
SEL_PRON_US = "#allMeanGroups .my_global_pron_area .pronounce_item .pronounce, .my_global_pron_area .pronounce_item .pronounce"
SEL_AUDIO_US = ".my_global_pron_area .listen_global_item.us"
# A "part_area" block + its sibling top-level .mean_list make up one MeaningGroup.
SEL_MEANING_TRAY = "#allMeanGroups, .mean_tray.important_words"
SEL_PART_AREA = ".part_area"
SEL_GROUP_POS = ".part_speech"
# Inside a MeaningGroup we walk down to .mean_item nodes that actually
# carry a .mean_desc (skipping the one wrapper layer Naver inserts).
SEL_SENSE_NODE = ".mean_item"  # filtered in code by has-mean_desc
SEL_SENSE_NUMBER = ":scope > .mean_desc > .num"
SEL_SENSE_GLOSS = ":scope > .mean_desc .cont .mean"
SEL_EXAMPLE_BLOCK = ":scope > .example"
SEL_EXAMPLE_ITEM = ".example_item"
SEL_EXAMPLE_SOURCE = "p.origin .text"
SEL_EXAMPLE_TRANSLATION = "p.translate .text"
SEL_RELATION_ROW = ":scope > .component_relation > .row"
SEL_RELATION_LABEL = "em.tit"
SEL_RELATION_ITEM = ".cont .item"
# ----------------------------------------------------------------------

WAIT_SELECTOR = "#allMeanGroups, .mean_tray.important_words, .entry_pronounce, .mean_list .mean_item .mean_desc"

log = logging.getLogger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")
_REFERENCE_RE = re.compile(r"\s*(?:\((?:=|→|->)\s*[^)]*\)|(?:=|→|->)\s*\S+)\s*")
_GLOSS_STOPWORDS = {
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


def lookup_url(word: str) -> str:
    from urllib.parse import quote

    return LOOKUP_URL.format(query=quote(word))


def parse(html: str, *, word: str, source_url: str) -> VocabularyEntry | None:
    entry, _ = parse_with_canonical(html, word=word, source_url=source_url)
    return entry


def parse_with_canonical(
    html: str, *, word: str, source_url: str
) -> tuple[VocabularyEntry | None, str]:
    """Same as parse() but also returns the canonical headword string.

    We always store the dictionary's headword (lemma) — typing
    'instantiates' saves 'instantiate', 'running' saves 'run'.
    """
    soup = make_soup(html)
    headword_node = first(soup, SEL_HEADWORD)
    canonical = text_or_empty(headword_node) or word
    headword = canonical

    reading = text_or_empty(first(soup, SEL_PRON_US))
    audio_url = _first_audio_url(soup, source_url)

    meaning_groups = _parse_meaning_groups(soup)
    if not meaning_groups:
        # Fallback: when Naver shows a search result list instead of an
        # entry page (typical for words with no primary entry, e.g.
        # "recalibration") we extract from the first matching .row.
        meaning_groups, fallback_canonical = _parse_search_result_rows(soup, word)
        if fallback_canonical:
            canonical = fallback_canonical
            headword = fallback_canonical
    if not meaning_groups and not reading:
        return None, canonical

    pos_top = [g.pos for g in meaning_groups if g.pos]
    synonyms = _aggregate_relations(meaning_groups, "synonyms")
    antonyms = _aggregate_relations(meaning_groups, "antonyms")

    entry = VocabularyEntry(
        language="en",
        word=headword,
        reading=reading or None,
        pronunciation_audio_url=audio_url,
        part_of_speech=pos_top,
        meaning_groups=meaning_groups,
        synonyms=synonyms,
        antonyms=antonyms,
        source_url=source_url,
        source_provider="naver_en",
    )
    entry.examples_flat = collect_examples_flat(entry)
    entry.meanings_summary = build_meanings_summary(entry)
    return entry, canonical


def cache_entry_needs_refresh(entry: VocabularyEntry) -> bool:
    if entry.source_provider != "naver_en":
        return False
    for group in entry.meaning_groups:
        for sense in group.senses:
            gloss = (sense.gloss or "").strip()
            if not gloss:
                continue
            cleaned = _clean_meaning_gloss(gloss)
            if not cleaned or cleaned != gloss:
                return True
    return False


def _first_audio_url(soup, base_url: str) -> str | None:
    """Naver renders pronunciations through a JS TTS API rather than a
    static <audio src>. We do not synthesize the URL — return None and
    let the user trigger native playback through the source page."""
    return None


def _aggregate_relations(meaning_groups: list[MeaningGroup], kind: str) -> list[str]:
    """Roll up synonyms/antonyms from every SubSense into an entry-level list."""
    out: list[str] = []
    seen: set[str] = set()
    for group in meaning_groups:
        for sense in group.senses:
            for sub in sense.sub_senses:
                values = getattr(sub, kind, []) or []
                for value in values:
                    if value and value not in seen:
                        seen.add(value)
                        out.append(value)
    return out


def _parse_search_result_rows(
    soup, word: str
) -> tuple[list[MeaningGroup], str]:
    """Fallback parser for the search-results list layout.

    Returns (meaning_groups, canonical_word). The canonical word is the
    headword of the first matching row — that's the lemma we save under.
    """
    groups_by_pos: dict[str, list[Sense]] = {}
    sense_counter: dict[str, int] = {}
    last_pos = ""
    canonical = ""

    typed_lower = word.lower()
    candidate_rows = _select_search_result_rows(soup, typed_lower)
    for row, row_word in candidate_rows:
        if not canonical:
            canonical = row_word
        for mean_item in row.select("ul.mean_list > li.mean_item"):
            mean_p = mean_item.find("p", class_="mean")
            if mean_p is None:
                continue
            wc_node = mean_p.find("span", class_="word_class")
            pos = text_or_empty(wc_node) if wc_node else ""
            # Strip the POS span out so the remaining text is the gloss.
            if wc_node is not None:
                wc_node.extract()
            gloss = _clean_meaning_gloss(text_or_empty(mean_p))
            if not gloss:
                continue
            # Some rows omit POS — inherit the most recent one so we
            # don't fragment the entry into a bunch of '[]' groups.
            if not pos:
                pos = last_pos
            else:
                last_pos = pos
            sense_counter[pos] = sense_counter.get(pos, 0) + 1
            groups_by_pos.setdefault(pos, []).append(
                Sense(number=sense_counter[pos], gloss=gloss, sub_senses=[])
            )

    groups = [
        MeaningGroup(pos=pos, senses=senses)
        for pos, senses in groups_by_pos.items()
    ]
    return groups, canonical


def _select_search_result_rows(soup, typed_lower: str):
    candidates: list[tuple[int, object, str]] = []
    for row in soup.select(".row"):
        link = row.select_one(".origin a.link, .origin .text")
        if link is None:
            continue
        if str(link.get("lang", "")).lower() not in {"", "en"}:
            continue
        row_word = link.get_text(" ", strip=True).strip()
        score = _search_row_match_score(row_word, typed_lower)
        if score is None:
            continue
        candidates.append((score, row, row_word))
    if not candidates:
        return []
    best_score = min(score for score, _, _ in candidates)
    best = [(row, row_word) for score, row, row_word in candidates if score == best_score]
    if best_score <= 1:
        return best
    return best[:1]


def _search_row_match_score(row_word: str, typed_lower: str) -> int | None:
    row_lower = (row_word or "").strip().lower()
    if not row_lower or not typed_lower:
        return None
    if row_lower == typed_lower:
        return 0
    if _simple_lemma_key(row_lower) == _simple_lemma_key(typed_lower):
        return 1
    # Last resort: let one near row rescue inflected or sparse search pages,
    # but never merge every surrounding phrase into the saved meaning list.
    if typed_lower in row_lower or row_lower in typed_lower:
        return 2
    return None


def _simple_lemma_key(value: str) -> str:
    text = re.sub(r"[^a-z]+", "", value.lower())
    for suffix in ("ies", "es", "s"):
        if len(text) > len(suffix) + 2 and text.endswith(suffix):
            if suffix == "ies":
                return text[: -len(suffix)] + "y"
            return text[: -len(suffix)]
    return text


def _parse_meaning_groups(soup) -> list[MeaningGroup]:
    """Walk the meaning tray, pairing each .part_area with its sibling
    .mean_list as one MeaningGroup."""
    tray = (
        first(soup, "#allMeanGroups")
        or first(soup, "#beginnerMeanGroups")
        or first(soup, ".mean_tray.important_words")
        or first(soup, ".mean_tray")
    )
    if tray is None:
        return []

    groups: list[MeaningGroup] = []
    current_pos = ""
    current_senses: list[Sense] = []
    sense_counter = 0

    for child in tray.children:
        if not getattr(child, "name", None):
            continue
        cls = child.get("class", []) or []
        if "part_area" in cls:
            if current_pos or current_senses:
                groups.append(MeaningGroup(pos=current_pos, senses=current_senses))
            current_pos = text_or_empty(first(child, SEL_GROUP_POS))
            current_senses = []
            sense_counter = 0
        elif "mean_list" in cls:
            for sense_node in _iter_sense_nodes(child):
                sense_counter += 1
                sense = _parse_sense(sense_node, sense_counter)
                if sense is not None:
                    current_senses.append(sense)

    if current_pos or current_senses:
        groups.append(MeaningGroup(pos=current_pos, senses=current_senses))
    return _renumber_groups(groups)


def _iter_sense_nodes(mean_list_node):
    """Yield every .mean_item that actually carries sense data.

    Naver uses two layouts:
      A) mean_item > mean_desc > num + cont > mean    (apple)
      B) mean_item > num + cont > mean                (jelly)

    Some entries also wrap senses in an outer mean_item that only
    contains another mean_list — we skip those wrappers.
    """
    for item in mean_list_node.find_all("li", class_="mean_item"):
        if item.find("div", class_="mean_desc", recursive=False):
            yield item
        elif item.find("span", class_="num", recursive=False):
            yield item


def _parse_sense(sense_node, fallback_number: int) -> Sense | None:
    # Layout A: data lives inside a .mean_desc wrapper.
    desc = sense_node.find("div", class_="mean_desc", recursive=False)
    if desc is not None:
        number_node = desc.find("span", class_="num")
        cont = desc.find("div", class_="cont")
    else:
        # Layout B: .num + .cont are direct children of mean_item.
        number_node = sense_node.find("span", class_="num", recursive=False)
        cont = sense_node.find("div", class_="cont", recursive=False)

    number = extract_number(number_node)
    gloss_node = cont.find("span", class_="mean") if cont else None
    gloss = _clean_meaning_gloss(text_or_empty(gloss_node))

    examples = _parse_examples(sense_node)
    sub_senses: list[SubSense] = []
    if examples:
        sub_senses.append(SubSense(label="", gloss="", examples=examples))

    syns, ants, refs = _parse_relations(sense_node)
    if sub_senses:
        sub_senses[0].synonyms = syns
        sub_senses[0].antonyms = ants
    elif syns or ants:
        sub_senses.append(SubSense(label="", gloss="", synonyms=syns, antonyms=ants))

    if not gloss and not sub_senses:
        return None
    return Sense(number=number or fallback_number, gloss=gloss, sub_senses=sub_senses)


def _renumber_groups(groups: list[MeaningGroup]) -> list[MeaningGroup]:
    for group in groups:
        for index, sense in enumerate(group.senses, start=1):
            sense.number = index
    return groups


def _clean_meaning_gloss(text: str) -> str:
    gloss = _normalize_gloss_text(text)
    if not gloss:
        return ""
    gloss = _REFERENCE_RE.sub(" ", gloss)
    gloss = re.sub(r"\s+", " ", gloss).strip(" .;")
    if not _is_usable_korean_gloss(gloss):
        return ""
    return gloss


def _normalize_gloss_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _is_usable_korean_gloss(gloss: str) -> bool:
    if not _HANGUL_RE.search(gloss):
        return False
    chunks = re.findall(r"[가-힣]+", gloss)
    meaningful = [chunk for chunk in chunks if chunk not in _GLOSS_STOPWORDS]
    return bool(meaningful)


def _parse_examples(sense_node) -> list[Example]:
    """Pull every .example_item under this sense's direct .example block."""
    block = sense_node.find("div", class_="example", recursive=False)
    if block is None:
        return []
    items: list[Example] = []
    for idx, ex_node in enumerate(block.find_all("div", class_="example_item")):
        src_node = ex_node.select_one("p.origin .text")
        trans_node = ex_node.select_one("p.translate .text")
        src = text_or_empty(src_node)
        trans = text_or_empty(trans_node)
        if not src and not trans:
            continue
        items.append(
            Example(
                source_text=src,
                source_text_plain=src,
                translation_ko=trans or None,
                order=idx,
            )
        )
    return items


def _parse_relations(sense_node) -> tuple[list[str], list[str], list[str]]:
    """Return (synonyms, antonyms, references) collected from
    .component_relation rows attached to this sense."""
    block = sense_node.find("ul", class_="component_relation", recursive=False)
    if block is None:
        return [], [], []
    syns: list[str] = []
    ants: list[str] = []
    refs: list[str] = []
    for row in block.find_all("li", class_="row", recursive=False):
        label_node = row.find("em", class_="tit")
        label_classes = " ".join(label_node.get("class", [])) if label_node else ""
        items = [
            text_or_empty(item)
            for item in row.select(".cont .item")
            if text_or_empty(item)
        ]
        if "synonym" in label_classes.lower():
            syns.extend(items)
        elif "antonym" in label_classes.lower():
            ants.extend(items)
        else:
            refs.extend(items)
    # Deduplicate while preserving order.
    return (
        dedup_preserve_order(syns),
        dedup_preserve_order(ants),
        dedup_preserve_order(refs),
    )
