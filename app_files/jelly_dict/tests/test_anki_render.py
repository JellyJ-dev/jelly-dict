from __future__ import annotations

from pathlib import Path
import re

import pytest

from app.anki import apkg_exporter, render, tsv_exporter
from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
)
from app.dictionary.parser_utils import make_soup, ruby_html


def _ja_entry() -> VocabularyEntry:
    entry = VocabularyEntry(
        language="ja",
        word="月日",
        reading="つきひ",
        part_of_speech=["명사"],
        meaning_groups=[
            MeaningGroup(
                pos="명사",
                senses=[
                    Sense(
                        number=1,
                        gloss="월일.",
                        sub_senses=[
                            SubSense(
                                label="a",
                                gloss="시일; 세월.",
                                examples=[
                                    Example(
                                        source_text="<ruby>月<rt>つき</rt></ruby><ruby>日<rt>ひ</rt></ruby>が経つ",
                                        source_text_plain="月日が経つ",
                                        translation_ko="시일이 지나다",
                                    )
                                ],
                                synonyms=["としつき"],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    entry.examples_flat = collect_examples_flat(entry)
    entry.meanings_summary = build_meanings_summary(entry)
    return entry


def _en_entry() -> VocabularyEntry:
    entry = VocabularyEntry(
        language="en",
        word="retention",
        reading="[ rɪˈtenʃn ]",
        part_of_speech=["Noun"],
        meaning_groups=[
            MeaningGroup(
                pos="Noun",
                senses=[
                    Sense(number=1, gloss="보유[유지]"),
                    Sense(number=2, gloss="기억(력)"),
                ],
            )
        ],
    )
    entry.meanings_summary = build_meanings_summary(entry)
    return entry


def _render_card_back_for_test(entry: VocabularyEntry) -> str:
    template = render.load_template("card_back.html")
    fields = render.fields_for_entry(entry)

    def replace_section(match: re.Match[str]) -> str:
        name = match.group(1)
        body = match.group(2)
        return body if fields.get(name) else ""

    html = re.sub(r"{{#(\w+)}}(.*?){{/\1}}", replace_section, template, flags=re.S)
    for key, value in fields.items():
        html = html.replace("{{" + key + "}}", value)
    return html


def test_render_meaning_detail_includes_pos_and_synonym_chip():
    html = render.render_meaning_detail(_ja_entry())
    assert "명사" in html
    assert "시일; 세월." in html
    assert "동의어" in html
    assert "としつき" in html


def test_render_keeps_ruby_html_in_examples():
    html = render.render_meaning_detail(_ja_entry())
    assert "<ruby>" in html


def test_render_escapes_non_ruby_example_html():
    entry = VocabularyEntry(
        language="en",
        word="x",
        examples_flat=[
            Example(
                source_text='<img src=x onerror=alert(1)><ruby>月<rt>つき</rt></ruby>',
                source_text_plain="plain",
            )
        ],
    )

    html = render.render_examples_html(entry)

    assert '<img src=x onerror=alert(1)>' not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<ruby>月<rt>つき</rt></ruby>" in html


def test_ruby_html_sanitizes_non_ruby_markup():
    soup = make_soup(
        '<div><ruby onclick="x">月<rt>つき</rt></ruby>'
        '<script>alert(1)</script><span data-x="1">日</span></div>'
    )

    html = ruby_html(soup.div)

    assert html == "<ruby>月<rt>つき</rt></ruby>日"
    assert "script" not in html
    assert "onclick" not in html


def test_fields_for_entry_has_all_required_fields():
    fields = render.fields_for_entry(_ja_entry())
    for key in render.FIELD_ORDER:
        assert key in fields


def test_english_card_omits_furigana_toggle():
    html = _render_card_back_for_test(_en_entry())
    assert "요미가나" not in html
    assert "ruby-toggle" not in html
    assert "예문 닫기" in html


def test_japanese_card_keeps_furigana_toggle():
    html = _render_card_back_for_test(_ja_entry())
    assert "요미가나" in html
    assert "ruby-toggle" in html
    assert "예문 닫기" in html


def test_tsv_export_writes_file(tmp_path: Path):
    out = tmp_path / "deck.tsv"
    count = tsv_exporter.export_tsv(out, [_ja_entry()])
    assert count == 1
    text = out.read_text(encoding="utf-8-sig")
    assert "#columns:" in text
    assert "月日" in text


def test_apkg_export_writes_file(tmp_path: Path):
    pytest.importorskip("genanki")
    out = tmp_path / "deck.apkg"
    count = apkg_exporter.export_apkg(out, [_ja_entry()], deck_name="Test")
    assert count == 1
    assert out.exists() and out.stat().st_size > 0


def test_apkg_guid_stable_across_runs():
    g1 = apkg_exporter._note_guid("ja", "月日")
    g2 = apkg_exporter._note_guid("ja", "月日")
    assert g1 == g2
    assert apkg_exporter._note_guid("ja", "月日") != apkg_exporter._note_guid("en", "apple")


def test_field_order_audio_fields_appended_at_end():
    # Existing field indexes must be preserved so older imported decks
    # keep working. New control/audio fields must come after the original
    # spreadsheet-backed fields.
    expected_prefix = (
        "Word", "Reading", "Language", "PartOfSpeech", "MeaningSummary",
        "MeaningDetail", "Examples", "ExampleTranslations", "Synonyms",
        "Antonyms", "Memo", "SourceURL",
    )
    assert render.FIELD_ORDER[: len(expected_prefix)] == expected_prefix
    assert render.FIELD_ORDER[len(expected_prefix):] == (
        "ShowRubyToggle",
        "WordAudio",
        "ShowFrontAudio",
        "ShowBackAudio",
    )


def test_fields_for_entry_audio_defaults_to_empty():
    fields = render.fields_for_entry(_en_entry())
    assert fields["WordAudio"] == ""
    assert fields["ShowFrontAudio"] == ""
    assert fields["ShowBackAudio"] == ""


def test_fields_for_entry_with_audio_map_renders_sound_tag():
    fields = render.fields_for_entry(
        _en_entry(),
        audio_map={
            "word": "en_kokoro_af-heart_abc123.mp3",
            "examples": [],
            "play_front": True,
            "play_back": True,
        },
    )
    assert fields["WordAudio"] == "[sound:en_kokoro_af-heart_abc123.mp3]"
    assert fields["ShowFrontAudio"] == "1"
    assert fields["ShowBackAudio"] == "1"


def test_fields_for_entry_renders_example_audio_in_detail():
    entry = _ja_entry()
    fields = render.fields_for_entry(
        entry,
        audio_map={
            "word": "ja_voicevox_word.mp3",
            "examples": ["ja_voicevox_example.mp3"],
            "play_front": True,
            "play_back": True,
        },
    )
    assert 'data-audio-bank="example-audio-0"' in fields["MeaningDetail"]
    assert (
        '<span id="example-audio-0" class="example-audio audio-bank">'
        "[sound:ja_voicevox_example.mp3]</span>"
    ) in fields["MeaningDetail"]
    assert "[sound:ja_voicevox_example.mp3]" in fields["Examples"]


def test_card_templates_support_click_to_play_audio():
    front = render.load_template("card_front.html")
    back = render.load_template("card_back.html")
    css = render.load_template("style.css")

    assert 'data-audio-bank="word-audio"' in front
    assert 'data-audio-bank="word-audio"' in back
    assert "document.querySelectorAll('[data-audio-bank]')" in front
    assert "document.querySelectorAll('[data-audio-bank]')" in back
    assert ".playable-audio" in css
    assert ".audio-bank" in css


def test_fields_for_entry_no_word_audio_disables_gates():
    fields = render.fields_for_entry(
        _en_entry(),
        audio_map={"word": "", "examples": [], "play_front": True, "play_back": True},
    )
    assert fields["WordAudio"] == ""
    assert fields["ShowFrontAudio"] == ""
    assert fields["ShowBackAudio"] == ""


def test_apkg_export_without_settings_has_no_media(tmp_path: Path):
    pytest.importorskip("genanki")
    out = tmp_path / "deck.apkg"
    count = apkg_exporter.export_apkg(
        out, [_ja_entry()], deck_name="Test", settings=None,
    )
    assert count == 1


def test_apkg_export_tts_disabled_skips_audio(tmp_path: Path):
    pytest.importorskip("genanki")
    from dataclasses import dataclass

    @dataclass
    class _S:
        tts_enabled: bool = False

    out = tmp_path / "deck.apkg"
    count = apkg_exporter.export_apkg(
        out, [_en_entry()], deck_name="Test", settings=_S(),
    )
    assert count == 1
