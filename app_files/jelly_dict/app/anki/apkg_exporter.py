"""APKG (genanki) exporter.

Two stable note types so re-imports update existing cards instead of
creating duplicates:
  - JellyDict::English  (model id MODEL_ID_EN)
  - JellyDict::Japanese (model id MODEL_ID_JA)

Note GUID = SHA1(language|word_key) -> repeated exports update in place.

When ``settings`` is provided and TTS is enabled, audio is generated for
each entry, packaged into the APKG's media bundle, and referenced from
the card templates via ``WordAudio`` / ``ExampleAudios`` fields.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Iterable

from app.anki.render import FIELD_ORDER, fields_for_entry, load_template
from app.core.errors import ExportError
from app.core.models import Language, VocabularyEntry, normalize_word_key

# Stable model IDs. Do not change: changing these splits a user's deck.
MODEL_ID_EN = 1_701_524_001
MODEL_ID_JA = 1_701_524_002
DECK_ID_DEFAULT = 1_701_524_100


def export_apkg(
    path: Path,
    entries: Iterable[VocabularyEntry],
    deck_name: str,
    settings=None,
    progress_callback=None,
) -> int:
    """Build an APKG package.

    ``progress_callback(current, total, word)`` is invoked per entry so
    the UI can render real progress. It runs on the calling thread (the
    export worker), and the callable should marshal to the UI thread
    itself if needed (Qt signals do this automatically).
    """
    try:
        import genanki
    except ImportError as exc:  # pragma: no cover
        raise ExportError(
            "genanki is not installed. Run `pip install genanki`."
        ) from exc

    front = load_template("card_front.html")
    back = load_template("card_back.html")
    css = load_template("style.css")

    fields = [{"name": name} for name in FIELD_ORDER]
    template = {"name": "Card 1", "qfmt": front, "afmt": back}

    model_en = genanki.Model(
        MODEL_ID_EN,
        "JellyDict::English",
        fields=fields,
        templates=[template],
        css=css,
    )
    model_ja = genanki.Model(
        MODEL_ID_JA,
        "JellyDict::Japanese",
        fields=fields,
        templates=[template],
        css=css,
    )

    deck = genanki.Deck(_deck_id(deck_name), deck_name)

    pipeline = None
    batch = None
    if settings is not None and getattr(settings, "tts_enabled", False):
        from app.anki.tts.pipeline import TTSBatch, TTSPipeline

        pipeline = TTSPipeline(settings)
        batch = TTSBatch()

    entries_list = list(entries)
    total = len(entries_list)
    count = 0
    for idx, entry in enumerate(entries_list, start=1):
        if progress_callback is not None:
            try:
                progress_callback(idx, total, entry.word)
            except Exception:
                pass  # progress callback failure must never break export
        model = model_en if entry.language == "en" else model_ja
        audio_map = _build_audio_map(entry, pipeline, batch, settings)
        values = fields_for_entry(entry, audio_map=audio_map)
        note = genanki.Note(
            model=model,
            fields=[values.get(name, "") for name in FIELD_ORDER],
            tags=[t.replace(" ", "_") for t in entry.tags if t.strip()],
            guid=_note_guid(entry.language, entry.word),
        )
        deck.add_note(note)
        count += 1

    # Engine credit is non-optional: licensed engines (e.g. VOICEVOX
    # character voices) require attribution per their TOS, so we always
    # write it into the deck description when applicable.
    if batch is not None and batch.credits:
        deck.description = "TTS: " + ", ".join(sorted(batch.credits))

    package = genanki.Package(deck)
    if batch is not None and batch.media_paths:
        # genanki accepts string paths and copies the basename into the bundle.
        package.media_files = [str(p) for p in dict.fromkeys(batch.media_paths)]

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp_path = _new_temp_path(path)
        try:
            package.write_to_file(str(temp_path))
            temp_path.replace(path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    except OSError as exc:
        raise ExportError(str(exc)) from exc
    return count


def _build_audio_map(entry, pipeline, batch, settings):
    if pipeline is None:
        return None
    word_path = pipeline.synthesize(entry.word, entry.language, batch)
    examples: list[str] = []
    if getattr(settings, "tts_play_examples", False):
        for ex in entry.examples_flat:
            text = ex.source_text_plain or ex.source_text or ""
            ex_path = pipeline.synthesize(text, entry.language, batch)
            examples.append(ex_path.name if ex_path else "")
    return {
        "word": word_path.name if word_path else "",
        "examples": examples,
        "play_front": getattr(settings, "tts_play_front", True),
        "play_back": getattr(settings, "tts_play_back", True),
    }


def _note_guid(language: Language, word: str) -> str:
    key = normalize_word_key(word, language)
    return hashlib.sha1(f"{language}|{key}".encode("utf-8")).hexdigest()[:16]


def _deck_id(deck_name: str) -> int:
    digest = hashlib.sha1(deck_name.encode("utf-8")).digest()
    return DECK_ID_DEFAULT ^ int.from_bytes(digest[:4], "big")


def _new_temp_path(path: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=path.suffix,
    ) as temp_file:
        return Path(temp_file.name)
