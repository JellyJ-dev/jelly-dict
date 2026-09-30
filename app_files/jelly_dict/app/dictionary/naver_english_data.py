"""Pure parsing and candidate selection for Naver's observed browser responses."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass

from app.core.errors import ParseError
from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
    sanitize_meaning_gloss,
)
from app.dictionary.parser_utils import deduplicate_group_examples

SEARCH_PATH = "/api3/enko/search"
ENTRY_PATH = "/api/v2/platform/enko/entry"
_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_ENTRY_ID = re.compile(r"[A-Za-z0-9]+")


def plain(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(_TAG.sub("", value)).split())


def word_form(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("·", "").replace("・", "").replace("’", "'").replace("‘", "'")
    return " ".join(value.split())


def word_key(value: str) -> str:
    return word_form(value).casefold()


def phrase_key(value: str) -> str:
    """Recognize a changed copula without dropping any content or negation."""
    words = word_key(value).split()
    if len(words) >= 3 and words[0] in {"am", "is", "are", "was", "were", "been", "being"}:
        words[0] = "be"
    return " ".join(words)


def passive_query(word: str) -> str | None:
    """One conservative fallback; let the dictionary resolve the participle."""
    words = phrase_key(word).split()
    if not 3 <= len(words) <= 8 or words[0] != "be":
        return None
    if words[2] not in {"from", "of", "to", "with", "by", "in", "on", "at", "for", "about"}:
        return None
    if not re.fullmatch(r"[a-z]+", words[1]):
        return None
    if not (len(words[1]) > 3 and words[1].endswith(("ed", "en"))) and words[1] not in {
        "known",
        "made",
        "found",
        "taught",
        "left",
        "built",
        "caught",
        "held",
        "lost",
        "put",
        "led",
        "fed",
    }:
        return None
    return " ".join(words[1:])


def definition(value: object) -> str:
    text = plain(value)
    if re.fullmatch(r"\(약어\s+[^()]+\)", text):
        return ""
    return sanitize_meaning_gloss(text, "en")


def dictionaries(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@dataclass(frozen=True)
class Candidate:
    entry_id: str
    word: str
    has_definition: bool


def search_word(payload: dict, word: str) -> str:
    """Accept a server correction only when both original-query markers agree."""
    try:
        actual = plain(payload["searchResultMap"]["searchResultListMap"]["WORD"]["query"])
    except (KeyError, TypeError) as exc:
        raise ParseError("dictionary search schema changed") from exc
    if word_key(actual) == word_key(word):
        return word
    correction = payload.get("searchMaybek")
    if (
        actual
        and word_key(plain(payload.get("query"))) == word_key(word)
        and isinstance(correction, dict)
        and word_key(plain(correction.get("query"))) == word_key(word)
        and word_key(actual)
        in {word_key(plain(correction.get(key))) for key in ("forceQuery", "errataQuery")}
    ):
        return actual
    raise ParseError("dictionary response does not match the query")


def search_candidates(data: dict, word: str) -> list[Candidate]:
    word = search_word(data, word)
    try:
        block = data["searchResultMap"]["searchResultListMap"]["WORD"]
        items = block["items"]
    except (KeyError, TypeError) as exc:
        raise ParseError("dictionary search schema changed") from exc
    if word_key(plain(block.get("query"))) != word_key(word):
        raise ParseError("dictionary response does not match the query")
    if not isinstance(items, list):
        raise ParseError("dictionary search items are invalid")
    ranked: list[tuple[int, int, int, int, Candidate]] = []
    for index, item in enumerate(dictionaries(items)):
        eid = plain(item.get("entryId"))
        name = plain(item.get("expEntry"))
        if not _ENTRY_ID.fullmatch(eid) or not name:
            continue
        if item.get("languageCode", "ENKO") != "ENKO":
            continue
        if item.get("destinationLink") != f"#/entry/enko/{eid}":
            continue
        exact = phrase_key(name) == phrase_key(word)
        match_type = str(item.get("matchType", ""))
        # Trust explicit dictionary lemma matches, never substring phrases.
        if not exact and match_type not in {"exact:entry", "exact:subEntry", "exact:revert"}:
            continue
        has_definition = any(
            definition(mean.get("value"))
            for group in dictionaries(item.get("meansCollector"))
            for mean in dictionaries(group.get("means"))
        )
        ranked.append(
            (
                0 if exact else 1,
                0 if word_form(name) == word_form(word) else 1,
                0 if has_definition else 1,
                index,
                Candidate(eid, name, has_definition),
            )
        )
    ranked.sort(key=lambda item: item[:4])
    return [item[-1] for item in ranked]


def open_search_entry(payload: dict, word: str) -> VocabularyEntry | None:
    """Use an exact OPEN result already in the response, without another host request."""
    return search_result_entry(payload, word, "OPEN")


def search_result_entry(
    payload: dict,
    word: str,
    block_name: str,
    *,
    entry_id: str | None = None,
    allow_article: bool = False,
) -> VocabularyEntry | None:
    """Parse verified definitions from a search block, preserving its source."""
    word = search_word(payload, word)
    blocks = payload["searchResultMap"]["searchResultListMap"]
    block = blocks.get(block_name)
    if block is None:
        return None
    if not isinstance(block, dict) or word_key(plain(block.get("query"))) != word_key(word):
        raise ParseError("open dictionary response does not match the query")
    if not isinstance(block.get("items"), list):
        raise ParseError("open dictionary search items are invalid")
    for item in dictionaries(block["items"]):
        eid = plain(item.get("entryId"))
        name = plain(item.get("expEntry"))
        if entry_id is not None and eid != entry_id:
            continue
        if not _ENTRY_ID.fullmatch(eid) or not name or item.get("languageCode") != "ENKO":
            continue
        exact = phrase_key(name) == phrase_key(word)
        article_variant = (
            allow_article and word_key(name) == "the " + word_key(word) and len(word.split()) >= 2
        )
        if not exact and not article_variant:
            continue
        # Validate the entire link, including ID. Never follow arbitrary result URLs.
        link = item.get("destinationLink")
        if link == f"#/entry/enko/{eid}":
            url = f"https://en.dict.naver.com/{link}"
        elif (
            block_name == "OPEN" and link == f"https://open-pro.dict.naver.com/_ivp/#/pfentry/{eid}"
        ):
            url = link
        else:
            continue
        groups = []
        for collector in dictionaries(item.get("meansCollector")):
            pos = plain(collector.get("partOfSpeech2") or collector.get("partOfSpeech"))
            group = MeaningGroup(pos)
            for mean in dictionaries(collector.get("means")):
                gloss = definition(mean.get("value"))
                if not gloss:
                    continue
                source = plain(mean.get("exampleOri"))
                examples = (
                    [Example(source, source, plain(mean.get("exampleTrans")) or None)]
                    if source
                    else []
                )
                group.senses.append(
                    Sense(len(group.senses) + 1, gloss, [SubSense(examples=examples)])
                )
            if group.senses:
                groups.append(group)
        if not groups:
            continue
        entry = VocabularyEntry(
            language="en",
            word=name,
            meaning_groups=groups,
            part_of_speech=[g.pos for g in groups if g.pos],
            source_url=url,
            source_provider="naver_open" if block_name == "OPEN" else "naver_en",
        )
        deduplicate_group_examples(entry.meaning_groups)
        entry.examples_flat = collect_examples_flat(entry)
        entry.meanings_summary = build_meanings_summary(entry)
        return entry
    return None


def entry_payload(data: dict, entry_id: str, expected_word: str) -> dict:
    entry = data.get("entry")
    if not isinstance(entry, dict) or entry.get("entry_id") != entry_id:
        raise ParseError("dictionary detail does not match the requested entry")
    names = [
        plain(member.get(key))
        for member in dictionaries(entry.get("members"))
        for key in ("entry_name", "show_full_name", "show_short_name")
    ]
    if word_key(expected_word) not in {word_key(name) for name in names}:
        raise ParseError("dictionary detail does not match the selected headword")
    if not isinstance(entry.get("means"), list):
        raise ParseError("dictionary meanings schema changed")
    return entry


def entry_parts(entry: dict) -> frozenset[str]:
    return frozenset(plain(p.get("part_ko_name")) for p in dictionaries(entry.get("parts"))) - {""}


def alternate_ids(entry: dict) -> list[str]:
    group = entry.get("group") or {}
    if not isinstance(group, dict):
        return []
    return [
        peer["entry_id"]
        for peer in dictionaries(group.get("groupEntrys"))
        if peer.get("dict_type") == "enko"
        and isinstance(peer.get("entry_id"), str)
        and _ENTRY_ID.fullmatch(peer["entry_id"])
        and peer["entry_id"] != entry.get("entry_id")
    ]


def _part_name(part: dict) -> str:
    label = part.get("part_name")
    if isinstance(label, str):
        try:
            names = json.loads(label)
        except ValueError:
            names = None
        if isinstance(names, dict) and names.get("en"):
            return plain(names["en"]).title()
    return plain(part.get("part_ko_name"))


def _examples(mean: dict) -> list[Example]:
    result = []
    for example in dictionaries(mean.get("examples")):
        source = plain(example.get("show_example") or example.get("origin_example"))
        if not source:
            continue
        translations = [
            plain(item.get("show_translation") or item.get("origin_translation"))
            for item in dictionaries(example.get("translations"))
            if item.get("language") in (None, "ko")
        ]
        result.append(Example(source, source, next((v for v in translations if v), None)))
    return result


def _reading(entry: dict) -> str | None:
    prons = [p for m in dictionaries(entry.get("members")) for p in dictionaries(m.get("prons"))]
    prons.sort(key=lambda p: p.get("pron_type") not in ("A", "pron_A"))
    for pron in prons:
        value = pron.get("show_pron_symbol") or pron.get("pron_symbol")
        if isinstance(value, str):
            value = re.sub(r"<sup>\s*\|\s*</sup>", "ˈ", value)
        reading = plain(value).strip("[] ")
        if reading:
            return reading
    return None


def parse_entry(entry: dict, canonical: str) -> VocabularyEntry:
    """Keep every POS and complete gloss; example-only senses are not definitions."""
    groups: dict[str, MeaningGroup] = {}
    all_examples: list[Example] = []
    synonyms: list[str] = []
    antonyms: list[str] = []
    for mean in dictionaries(entry.get("means")):
        part = mean.get("part") if isinstance(mean.get("part"), dict) else {}
        pos = _part_name(part)
        gloss = definition(mean.get("show_mean") or mean.get("origin_mean"))
        examples = _examples(mean)
        all_examples.extend(examples)
        sub = SubSense(examples=examples)
        for relation in dictionaries(mean.get("relateds")):
            label = relation.get("related_type")
            value = plain(relation.get("show_content") or relation.get("related_content"))
            if value and label in {"synonym", "antonym", "opposite_en"}:
                target = sub.synonyms if label == "synonym" else sub.antonyms
                target.append(value)
                (synonyms if label == "synonym" else antonyms).append(value)
        if not gloss:
            continue
        group = groups.setdefault(pos, MeaningGroup(pos))
        group.senses.append(Sense(len(group.senses) + 1, gloss, [sub]))
    result = VocabularyEntry(
        language="en",
        word=canonical.replace("·", "").replace("・", ""),
        reading=_reading(entry),
        part_of_speech=[p for p in groups if p],
        meaning_groups=list(groups.values()),
        source_url=f"https://en.dict.naver.com/#/entry/enko/{entry['entry_id']}",
        source_provider="naver_en",
        synonyms=list(dict.fromkeys(synonyms)),
        antonyms=list(dict.fromkeys(antonyms)),
    )
    deduplicate_group_examples(result.meaning_groups)
    result.examples_flat = collect_examples_flat(result)
    # Keep source examples even when a cross-reference-only sense has no gloss.
    seen = {(e.source_text_plain, e.translation_ko) for e in result.examples_flat}
    for example in all_examples:
        pair = example.source_text_plain, example.translation_ko
        if pair not in seen:
            seen.add(pair)
            result.examples_flat.append(example)
    for index, example in enumerate(result.examples_flat):
        example.order = index
    result.meanings_summary = build_meanings_summary(result)
    return result
