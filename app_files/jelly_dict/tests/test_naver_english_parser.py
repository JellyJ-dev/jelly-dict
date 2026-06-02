"""Characterization tests for the Naver English parser.

Backed by saved HTML in tests/fixtures/. These guard against parser
regressions during refactors — none of these assertions touch the
network. If Naver's page structure changes the fixtures can be
re-captured with `python scripts/dump_entry.py <URL>` and copied over.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.dictionary import naver_english

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_apple_entry_page_parses_full_structure():
    html = _load("naver_en_apple.html")
    entry, canonical = naver_english.parse_with_canonical(
        html, word="apple", source_url="https://en.dict.naver.com/#/search?query=apple"
    )
    assert entry is not None
    assert entry.word == "apple"
    assert canonical == "apple"
    assert entry.reading and "æpl" in entry.reading
    assert entry.part_of_speech == ["Noun"]
    assert entry.meanings_summary.startswith("[Noun]")
    assert "사과" in entry.meanings_summary
    # At least one example pair is captured.
    flat = entry.examples_flat
    assert len(flat) >= 1
    assert any("apple" in ex.source_text_plain.lower() for ex in flat)
    assert any("사과" in (ex.translation_ko or "") for ex in flat)


def test_jelly_entry_page_handles_flat_layout_variant():
    """jelly's mean_item layout is flatter than apple's (no .mean_desc
    wrapper). The parser must support both."""
    html = _load("naver_en_jelly.html")
    entry, _ = naver_english.parse_with_canonical(
        html, word="jelly", source_url="x"
    )
    assert entry is not None
    assert entry.word == "jelly"
    senses = entry.meaning_groups[0].senses
    assert len(senses) >= 3
    glosses = " ".join(s.gloss for s in senses)
    assert "젤리" in glosses


def test_recalibration_falls_back_to_search_result_rows():
    """recalibration has no main entry page; the parser must still pull
    POS + Korean meaning from the search result rows."""
    html = _load("naver_en_recalibration.html")
    entry, _ = naver_english.parse_with_canonical(
        html, word="recalibration", source_url="x"
    )
    assert entry is not None
    assert entry.word == "recalibration"
    assert entry.part_of_speech and entry.part_of_speech[0] == "Noun"
    assert "재교정" in entry.meanings_summary or "재측정" in entry.meanings_summary
    assert "Unit Measures" not in entry.meanings_summary
    assert "빈번한 재보정" not in entry.meanings_summary
    assert "Plural form" not in entry.meanings_summary


def test_search_fallback_prefers_exact_headword_rows():
    html = _load("naver_en_recalibration.html")
    entry, _ = naver_english.parse_with_canonical(
        html, word="recalibration", source_url="x"
    )
    assert entry is not None

    glosses = [sense.gloss for sense in entry.meaning_groups[0].senses]

    assert glosses == ["재교정", "재측정"]


def test_meaning_tray_drops_cross_reference_and_english_definition_noise():
    html = """
    <div id="allMeanGroups">
      <div class="part_area"><span class="part_speech">Noun</span></div>
      <ul class="mean_list">
        <li class="mean_item">
          <div class="mean_desc">
            <span class="num">1</span>
            <div class="cont"><span class="mean">특히 美 (= artefact)</span></div>
          </div>
        </li>
        <li class="mean_item">
          <div class="mean_desc">
            <span class="num">2</span>
            <div class="cont"><span class="mean">인공물[가공품]</span></div>
          </div>
        </li>
        <li class="mean_item" lang="en">
          <div class="mean_desc">
            <span class="num">3</span>
            <div class="cont">
              <span class="mean" lang="en">
                n. a simple object that was made by people in the past UK: artefact
              </span>
            </div>
          </div>
        </li>
        <li class="mean_item">
          <div class="mean_desc">
            <span class="num">4</span>
            <div class="cont">
              <span class="mean">의학 흐름인공물, 흐름허상, 유동인공물 (→ artifact)</span>
            </div>
          </div>
        </li>
      </ul>
    </div>
    """
    entry, _ = naver_english.parse_with_canonical(html, word="artifact", source_url="x")
    assert entry is not None

    glosses = [sense.gloss for sense in entry.meaning_groups[0].senses]

    assert glosses == ["인공물[가공품]", "의학 흐름인공물, 흐름허상, 유동인공물"]
    assert "artefact" not in entry.meanings_summary.lower()
    assert "artifact" not in entry.meanings_summary.lower()
    assert "n. a simple object" not in entry.meanings_summary


@pytest.mark.parametrize(
    "fixture, word",
    [
        ("naver_en_apple.html", "apple"),
        ("naver_en_jelly.html", "jelly"),
        ("naver_en_recalibration.html", "recalibration"),
    ],
)
def test_parser_always_returns_canonical_string(fixture, word):
    html = _load(fixture)
    entry, canonical = naver_english.parse_with_canonical(
        html, word=word, source_url="x"
    )
    assert canonical
    if entry is not None:
        assert entry.word.lower() == word.lower()
