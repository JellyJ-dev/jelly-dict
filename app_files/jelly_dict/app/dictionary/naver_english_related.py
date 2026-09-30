"""Offer observed component headwords without treating them as phrase definitions."""

from __future__ import annotations

import re

from app.dictionary import naver_english_data as data

_WORD = re.compile(r"[a-z]+(?:['-][a-z]+)*")
_ID = re.compile(r"[A-Za-z0-9]+")
_FUNCTION_WORDS = frozenset(
    "a an the be am is are was were been being do does did have has had "
    "to of for from in on at by with about into onto out off over under "
    "as and or but if than that this these those it its I you he she we they "
    "me him her us them my your his our their not no nor can could will would "
    "shall should may might must".lower().split()
)
_INFLECTIONS = frozenset(
    {
        "past tense",
        "past participle",
        "present participle",
        "3rd person singular present",
        "plural",
        "comparative",
        "superlative",
    }
)


def _contains(tokens: list[str], parts: list[str]) -> bool:
    return any(tokens[i : i + len(parts)] == parts for i in range(len(tokens) - len(parts) + 1))


def _match_kind(item: dict, tokens: list[str], parts: list[str]) -> int | None:
    if _contains(tokens, parts):
        return 0
    # Use only inflections explicitly attached to this observed headword.
    # Noun/verb/adverb derivations and synonyms aren't spelling variants.
    if len(parts) != 1:
        return None
    for form in data.dictionaries(item.get("expAliasEntrySearchList")):
        if data.word_key(data.plain(form.get("conjTypeCode"))) not in _INFLECTIONS:
            continue
        value = data.word_key(data.plain(form.get("conjValue")))
        if _WORD.fullmatch(value) and value in tokens and value not in _FUNCTION_WORDS:
            return 1
    return None


def search_words(payload: dict, word: str) -> list[str]:
    """Return observed components, including their source-declared inflections.

    No stemming or extra requests: spelling correction has its own path.
    Function-word-only matches and longer/unrelated phrases aren't useful here.
    """
    query = data.search_word(payload, word)
    tokens = _WORD.findall(data.word_key(query))
    if len(tokens) < 2:
        return []
    blocks = payload["searchResultMap"]["searchResultListMap"]
    ranked: list[tuple[int, int, int, int, str]] = []
    for source, key in enumerate(("WORD", "OPEN")):
        block = blocks.get(key)
        if not isinstance(block, dict) or data.word_key(
            data.plain(block.get("query"))
        ) != data.word_key(query):
            continue
        for index, item in enumerate(data.dictionaries(block.get("items"))):
            eid = data.plain(item.get("entryId"))
            name = data.plain(item.get("expEntry"))
            normalized = data.word_key(name)
            parts = normalized.split()
            if (
                not _ID.fullmatch(eid)
                or item.get("languageCode") != "ENKO"
                or not parts
                or not all(_WORD.fullmatch(p) for p in parts)
                or not (set(parts) - _FUNCTION_WORDS)
                or normalized == data.word_key(query)
            ):
                continue
            match_kind = _match_kind(item, tokens, parts)
            if match_kind is None:
                continue
            links = {f"#/entry/enko/{eid}"}
            if key == "OPEN":
                links.add(f"https://open-pro.dict.naver.com/_ivp/#/pfentry/{eid}")
            if item.get("destinationLink") not in links:
                continue
            if not any(
                data.definition(mean.get("value"))
                for group in data.dictionaries(item.get("meansCollector"))
                for mean in data.dictionaries(group.get("means"))
            ):
                continue
            ranked.append((match_kind, -len(parts), source, index, name))
    result: list[str] = []
    seen: set[str] = set()
    for *_, name in sorted(ranked):
        key = data.word_key(name)
        if key not in seen:
            result.append(name)
            seen.add(key)
        if len(result) == 5:
            break
    return result
