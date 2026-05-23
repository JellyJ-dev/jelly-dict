"""Characterization tests for the Naver Japanese parser.

Uses the saved 蘇る (yomigaeru) page in tests/fixtures/. The fixture is
chosen because it exercises the full feature surface: kanji + middle-dot
variant headword (蘇る·甦る), typed variant saving, conjugated POS label (5단활용 자동사), and
furigana-bearing examples.
"""
from __future__ import annotations

from pathlib import Path

from app.dictionary import naver_japanese

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_yomigaeru_parses_canonical_headword_and_reading():
    html = _load("naver_ja_yomigaeru.html")
    entry, canonical = naver_japanese.parse_with_canonical(
        html, word="蘇る", source_url="x"
    )
    assert entry is not None
    # Naver publishes both kanji forms separated by a middle dot, but the
    # saved card should use the exact variant the user searched for.
    assert canonical == "蘇る·甦る"
    assert entry.word == "蘇る"
    assert entry.reading == "よみがえる"
    assert entry.part_of_speech == ["5단활용 자동사"]


def test_yomigaeru_meanings_summary_lists_korean_glosses():
    html = _load("naver_ja_yomigaeru.html")
    entry, _ = naver_japanese.parse_with_canonical(
        html, word="蘇る", source_url="x"
    )
    assert entry is not None
    summary = entry.meanings_summary
    assert summary.startswith("[5단활용 자동사]")
    # The page lists three senses; at least the first one survives.
    assert "되살아나다" in summary or "소생하다" in summary


def test_yomigaeru_examples_have_clean_plain_text_no_cjk_spaces():
    """Naver wraps each character in its own span so naive text
    extraction yields '月 日 が 経 つ'. The parser collapses adjacent
    CJK characters so plain text reads naturally."""
    html = _load("naver_ja_yomigaeru.html")
    entry, _ = naver_japanese.parse_with_canonical(
        html, word="蘇る", source_url="x"
    )
    assert entry is not None
    plains = [ex.source_text_plain for ex in entry.examples_flat]
    assert plains, "expected at least one example"
    for plain in plains:
        assert not _has_cjk_pair_with_space(plain), (
            f"plain text still has space-separated CJK chars: {plain!r}"
        )


def _has_cjk_pair_with_space(text: str) -> bool:
    import re

    return bool(
        re.search(r"[぀-ゟ゠-ヿ一-鿿]\s+[぀-ゟ゠-ヿ一-鿿]", text)
    )
