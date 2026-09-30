from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.anki import apkg_exporter, tsv_exporter
from app.core.models import VocabularyEntry
from app.core.settings import Settings


class AnkiExportWriter:
    def export_tsv(
        self,
        output_path: Path,
        entries: list[VocabularyEntry],
    ) -> int:
        return tsv_exporter.export_tsv(output_path, entries)

    def export_apkg(
        self,
        output_path: Path,
        entries: list[VocabularyEntry],
        deck_name: str,
        *,
        settings: Settings,
        progress_callback: Callable | None = None,
    ) -> int:
        return apkg_exporter.export_apkg(
            output_path,
            entries,
            deck_name,
            settings=settings,
            progress_callback=progress_callback,
        )
