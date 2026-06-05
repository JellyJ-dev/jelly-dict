from __future__ import annotations

from app.core.models import MeaningGroup, Sense, SubSense
from app.dictionary import parser_utils


def test_strip_furigana_removes_rt_and_collapses_cjk_spacing():
    soup = parser_utils.make_soup("<ruby>食<rt>た</rt>べ る</ruby>")

    assert parser_utils.strip_furigana(soup.ruby) == "食べる"


def test_ruby_html_preserves_ruby_and_drops_scripts():
    soup = parser_utils.make_soup(
        "<span><ruby>食<rt>た</rt></ruby><script>x()</script>&</span>"
    )

    assert parser_utils.ruby_html(soup.span) == "<ruby>食<rt>た</rt></ruby>&amp;"


def test_aggregate_relations_deduplicates_in_order():
    groups = [
        MeaningGroup(
            senses=[
                Sense(sub_senses=[
                    SubSense(synonyms=["a", "b"]),
                    SubSense(synonyms=["b", "c"]),
                ])
            ]
        )
    ]

    assert parser_utils.aggregate_relations(groups, "synonyms") == ["a", "b", "c"]


def test_common_prefix_len():
    assert parser_utils.common_prefix_len("running", "runner") == 4
    assert parser_utils.common_prefix_len("apple", "banana") == 0
