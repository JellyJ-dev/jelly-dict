"""Read exact English translations from the search response's KOEN section."""

from __future__ import annotations

import re

from app.core.errors import ParseError
from app.core.models import Example, MeaningGroup, Sense, VocabularyEntry, build_meanings_summary
from app.dictionary import naver_english_data as data

_PREPOSITIONS = frozenset(
    "for to of from with at in on by about against over under into onto upon "
    "through across after before between among without within toward towards".split()
)
_LEADING_LABEL = re.compile(r"^(?:\[([^\[\]]+)\]|\(([^()]+)\))\s*")
_REGISTER_LABELS = frozenset({"formal", "informal", "literary", "slang", "technical"})


def _translation_choices(text: str) -> list[str]:
    """Split dictionary alternatives, never commas inside usage annotations."""
    stack: list[str] = []
    result: list[str] = []
    start = 0
    for i, char in enumerate(text):
        if char in "([":
            stack.append(char)
        elif char in ")]":
            if not stack or stack.pop() != {")": "(", "]": "["}[char]:
                return []
        elif char in ",;" and not stack:
            result.append(text[start:i].strip())
            start = i + 1
    return [] if stack else [*result, text[start:].strip()]


def _matches_translation(value: object, query: str) -> bool:
    """Match complete alternatives such as 'candidate (for)', not substrings.

    Only explicit trailing preposition notation is expanded. Content words,
    negation, objects, and word order remain intact; no meanings are synthesized.
    """
    source = data.word_form(data.plain(value))
    text = source.casefold()
    expected = data.word_key(query)
    if text == expected:
        return True
    # Explicit abbreviation expansions, e.g. AI (artificial intelligence).
    abbreviation = data.word_form(query)
    if re.fullmatch(r"[A-Z]{2,8}", abbreviation):
        expanded = re.fullmatch(re.escape(abbreviation) + r"\s*\(([A-Za-z ]+)\)", source)
        if expanded:
            words = [w for w in expanded[1].split() if w.lower() not in {"of", "the", "and"}]
            if len(words) >= 2 and "".join(w[0].upper() for w in words) == abbreviation:
                return True
    for choice in _translation_choices(text):
        while label := _LEADING_LABEL.match(choice):
            content = label[1] or label[2]
            korean_label = re.search(r"[가-힣]", content) and not re.search(r"[a-z]", content)
            if not korean_label and content not in _REGISTER_LABELS:
                break
            choice = choice[label.end() :]
        if choice.endswith(".") and not choice.endswith(".."):
            choice = choice[:-1].strip()
        if choice == expected:
            return True
        notation = re.fullmatch(r"([a-z][a-z '\-]*)\s*\(([a-z /]+)\)", choice)
        if not notation:
            continue
        prepositions = [p.strip() for p in notation[2].split("/")]
        if not all(p in _PREPOSITIONS for p in prepositions):
            continue
        if any(f"{notation[1].strip()} {p}" == expected for p in prepositions):
            return True
    return False


def search_entry(payload: dict, query: str) -> VocabularyEntry | None:
    query = data.search_word(payload, query)
    blocks = payload["searchResultMap"]["searchResultListMap"]
    block = blocks.get("MEANING")
    if block is None:
        return None
    if not isinstance(block, dict) or data.word_key(
        data.plain(block.get("query"))
    ) != data.word_key(query):
        raise ParseError("meaning search response does not match the query")
    if not isinstance(block.get("items"), list):
        raise ParseError("meaning search items are invalid")
    for item in data.dictionaries(block["items"]):
        # A Korean dictionary's complete English translation must match. A
        # sentence merely containing the query cannot define the shorter phrase.
        if item.get("languageCode") != "KOEN" or item.get("matchType") != "exact:meaning":
            continue
        eid = data.plain(item.get("entryId"))
        if not re.fullmatch(r"[A-Za-z0-9]+", eid):
            continue
        if item.get("destinationLink") != f"#/entry/koen/{eid}":
            continue
        gloss = data.definition(item.get("expEntry"))
        if not re.search(r"[가-힣]", gloss):
            continue
        matches = any(
            _matches_translation(mean.get("value"), query)
            for group in data.dictionaries(item.get("meansCollector"))
            for mean in data.dictionaries(group.get("means"))
        )
        if not matches:
            continue
        entry = VocabularyEntry(
            language="en",
            word=data.plain(query),
            meaning_groups=[MeaningGroup("", [Sense(1, gloss)])],
            source_url=f"https://en.dict.naver.com/#/entry/koen/{eid}",
            source_provider="naver_en",
        )
        entry.meanings_summary = build_meanings_summary(entry)
        # These are examples of the whole queried expression, not additional
        # definitions or invented translations. Keep them outside a specific sense.
        entry.examples_flat = _search_examples(blocks.get("EXAMPLE"), query)
        return entry
    return None


def _search_examples(block: object, query: str) -> list[Example]:
    if not isinstance(block, dict) or data.word_key(
        data.plain(block.get("query"))
    ) != data.word_key(query):
        return []
    pattern = re.compile(r"(?<!\w)" + re.escape(data.word_key(query)) + r"(?!\w)")
    result: list[Example] = []
    seen: set[tuple[str, str]] = set()
    for item in data.dictionaries(block.get("items")):
        if (
            item.get("exampleLangCode") != "ENKO"
            or str(item.get("example1Lang")) != "2"
            or str(item.get("example2Lang")) != "1"
        ):
            continue
        source = data.plain(item.get("expExample1"))
        translation = data.plain(item.get("expExample2"))
        pair = source, translation
        if not translation or not pattern.search(data.word_key(source)) or pair in seen:
            continue
        seen.add(pair)
        result.append(Example(source, source, translation, len(result)))
        if len(result) == 3:
            break
    return result
