"""Renders the nested meaning structure into the HTML used by Anki cards."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from pathlib import Path

from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
    build_meanings_summary,
)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_ALLOWED_EXAMPLE_HTML_TAGS = frozenset({"ruby", "rt", "rp"})


def load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def render_meaning_detail(
    entry: VocabularyEntry,
    example_audios: list[str] | None = None,
) -> str:
    """Render meaning_groups into the structured HTML the Anki card expects."""
    parts: list[str] = []
    audio_index = [0]
    for group in entry.meaning_groups:
        parts.append('<div class="meaning-group">')
        if group.pos:
            parts.append(f'<div class="pos">{escape(group.pos)}</div>')
        for sense in group.senses:
            parts.append(_render_sense(sense, example_audios, audio_index))
        parts.append("</div>")
    return "".join(parts)


def _render_sense(
    sense: Sense,
    example_audios: list[str] | None = None,
    audio_index: list[int] | None = None,
) -> str:
    out: list[str] = ['<div class="sense">']
    label = f"{sense.number}." if sense.number else ""
    if label or sense.gloss:
        out.append(
            f'<div><span class="sense-label">{escape(label)}</span> '
            f'{escape(sense.gloss)}</div>'
        )
    for sub in sense.sub_senses:
        out.append(_render_sub_sense(sub, example_audios, audio_index))
    out.append("</div>")
    return "".join(out)


def _render_sub_sense(
    sub: SubSense,
    example_audios: list[str] | None = None,
    audio_index: list[int] | None = None,
) -> str:
    out: list[str] = ['<div class="sub-sense">']
    label = f"{sub.label}." if sub.label else ""
    out.append(
        f'<div><span class="sub-label">{escape(label)}</span> '
        f'{escape(sub.gloss)}</div>'
    )
    if sub.examples:
        out.append('<div class="examples">')
        for ex in sub.examples:
            audio = None
            if example_audios is not None and audio_index is not None:
                idx = audio_index[0]
                if idx < len(example_audios):
                    audio = example_audios[idx]
                audio_index[0] = idx + 1
            audio_id = f"example-audio-{idx}" if audio else None
            out.append(_render_example(ex, audio, audio_id))
        out.append("</div>")
    if sub.synonyms:
        out.append('<div class="synonyms">')
        out.append('<span class="chip-label">동의어</span>')
        for s in sub.synonyms:
            out.append(f'<span class="chip">{escape(s)}</span>')
        out.append("</div>")
    if sub.antonyms:
        out.append('<div class="synonyms">')
        out.append('<span class="chip-label">반의어</span>')
        for s in sub.antonyms:
            out.append(f'<span class="chip">{escape(s)}</span>')
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


def _render_example(
    ex: Example,
    audio_filename: str | None = None,
    audio_id: str | None = None,
) -> str:
    source = _sanitize_example_source(ex.source_text, ex.source_text_plain)
    source_attrs = 'class="example-source"'
    if audio_filename and audio_id:
        source_attrs = (
            'class="example-source playable-audio" '
            f'data-audio-bank="{escape(audio_id)}" role="button" tabindex="0"'
        )
    parts = [
        '<div class="example">',
        '<div class="example-head">',
        f"<span {source_attrs}>{source}</span>",
    ]
    if audio_filename and audio_id:
        # Anki's [sound:...] tag becomes a native replay button + autoplay
        # marker. We rely on it instead of HTML5 <audio> because the new
        # Audio() URL resolution is unreliable inside Anki's webview.
        parts.append(
            f'<span id="{escape(audio_id)}" class="example-audio audio-bank">'
            f"[sound:{audio_filename}]</span>"
        )
    parts.append("</div>")
    if ex.translation_ko:
        parts.append(
            f'<span class="example-trans">{escape(ex.translation_ko)}</span>'
        )
    parts.append("</div>")
    return "".join(parts)


def _sanitize_example_source(source_text: str, plain_text: str) -> str:
    """Render example source text while preserving only ruby markup.

    Japanese parser output intentionally carries sanitized ``<ruby>`` /
    ``<rt>`` markup. Other paths (Excel import, preview editing, manual
    data) may also populate ``source_text`` with plain user text, so the
    Anki renderer is the final trust boundary.
    """
    if not source_text:
        return escape(plain_text or "")
    sanitizer = _RubyOnlyHTMLSanitizer()
    sanitizer.feed(source_text)
    sanitizer.close()
    return sanitizer.html()


class _RubyOnlyHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []

    def html(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _ALLOWED_EXAMPLE_HTML_TAGS:
            self._parts.append(f"<{tag}>")
            return
        self._parts.append(escape(self.get_starttag_text() or f"<{tag}>"))

    def handle_endtag(self, tag: str) -> None:
        if tag in _ALLOWED_EXAMPLE_HTML_TAGS:
            self._parts.append(f"</{tag}>")
            return
        self._parts.append(escape(f"</{tag}>"))

    def handle_data(self, data: str) -> None:
        self._parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._parts.append(escape(f"<!--{data}-->"))


def render_examples_html(
    entry: VocabularyEntry,
    example_audios: list[str] | None = None,
) -> str:
    parts: list[str] = []
    for idx, ex in enumerate(entry.examples_flat):
        audio = (
            example_audios[idx]
            if example_audios is not None and idx < len(example_audios)
            else None
        )
        audio_id = f"example-audio-flat-{idx}" if audio else None
        parts.append(_render_example(ex, audio, audio_id))
    return "".join(parts)


def render_translations_html(entry: VocabularyEntry) -> str:
    return "<br>".join(
        escape(ex.translation_ko or "") for ex in entry.examples_flat
    )


def fields_for_entry(
    entry: VocabularyEntry,
    audio_map: dict | None = None,
) -> dict[str, str]:
    """Return the dict of Anki note fields for an entry.

    ``audio_map``, when provided, has the shape:
        {"word": "<filename.mp3>", "examples": ["<f1.mp3>", "", ...],
         "play_front": True, "play_back": True}
    The filenames are bare basenames (no path) — they live in the APKG
    media bundle. ``WordAudio`` stores Anki's native ``[sound:...]`` tag,
    not just the filename, so Anki's importer recognizes the field as a
    media reference and copies the file into ``collection.media``.
    None/missing keys mean no audio for that slot.
    """
    summary = entry.meanings_summary or build_meanings_summary(entry)
    audio_map = audio_map or {}
    word_audio_filename = audio_map.get("word") or ""
    word_audio = f"[sound:{word_audio_filename}]" if word_audio_filename else ""
    example_audios: list[str] = audio_map.get("examples") or []
    play_front = "1" if (word_audio and audio_map.get("play_front")) else ""
    play_back = "1" if (word_audio and audio_map.get("play_back")) else ""
    return {
        "Word": entry.word,
        "Reading": entry.reading or "",
        "Language": "EN" if entry.language == "en" else "JA",
        "ShowRubyToggle": "1" if entry.language == "ja" else "",
        "PartOfSpeech": ", ".join(entry.part_of_speech),
        "MeaningSummary": escape(summary),
        "MeaningDetail": render_meaning_detail(entry, example_audios),
        "Examples": render_examples_html(entry, example_audios),
        "ExampleTranslations": render_translations_html(entry),
        "Synonyms": ", ".join(escape(s) for s in entry.synonyms),
        "Antonyms": ", ".join(escape(s) for s in entry.antonyms),
        "Memo": escape(entry.memo or "").replace("\n", "<br>"),
        "SourceURL": entry.source_url or "",
        # Audio fields — appended to FIELD_ORDER so existing card model IDs
        # stay valid. Empty string means no audio.
        "WordAudio": word_audio,
        "ShowFrontAudio": play_front,
        "ShowBackAudio": play_back,
    }


FIELD_ORDER: tuple[str, ...] = (
    "Word",
    "Reading",
    "Language",
    "PartOfSpeech",
    "MeaningSummary",
    "MeaningDetail",
    "Examples",
    "ExampleTranslations",
    "Synonyms",
    "Antonyms",
    "Memo",
    "SourceURL",
    # Append-only — preserves existing field indexes for users who
    # already imported a deck from an earlier version.
    "ShowRubyToggle",
    "WordAudio",
    "ShowFrontAudio",
    "ShowBackAudio",
)
