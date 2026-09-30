"""Bundles current Excel rows into Anki TSV/APKG output."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from app.core.diagnostics import diagnostic_operation
from app.core.domain import WorkbookRevision
from app.core.entry_flat_codec import row_data_to_entry
from app.core.meaning_display import replace_nested_examples
from app.core.models import (
    VocabularyEntry,
    build_meanings_summary,
)
from app.core.settings import (
    AppSettings,
    PathSettings,
    SettingsDraft,
    settings_snapshot,
)
from app.services.ports import (
    ExportCachePort,
    ExportSourcePort,
    ExportWriterPort,
    PathSettingsPort,
    TtsRuntimeSettingsPort,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportSnapshot:
    language: str
    path: Path | None
    source_revision: WorkbookRevision | None
    entry_jsons: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.entry_jsons)

    def entries(self) -> list[VocabularyEntry]:
        return [VocabularyEntry.from_json(payload) for payload in self.entry_jsons]


class ExportPreparationError(RuntimeError):
    def __init__(self, path: Path | None, cause: BaseException) -> None:
        self.path = path
        self.cause = cause
        location = str(path) if path is not None else "Excel 경로"
        super().__init__(f"내보내기 데이터를 준비하지 못했습니다: {location}: {cause}")


class ExportService:
    def __init__(
        self,
        settings: AppSettings | SettingsDraft | PathSettings,
        cache: ExportCachePort,
        source: ExportSourcePort,
        writer: ExportWriterPort,
        *,
        tts_settings: TtsRuntimeSettingsPort | None = None,
    ) -> None:
        if tts_settings is None:
            snapshot = settings_snapshot(settings, validate=False)  # type: ignore[arg-type]
            self._paths: PathSettingsPort = snapshot.paths
            self._tts_settings: TtsRuntimeSettingsPort = snapshot.tts_runtime()
        else:
            self._paths = settings
            self._tts_settings = tts_settings
        self._cache = cache
        self._source = source
        self._writer = writer

    @property
    def cache(self) -> ExportCachePort:
        return self._cache

    def with_settings(
        self,
        settings: AppSettings | SettingsDraft,
    ) -> "ExportService":
        snapshot = settings_snapshot(settings)
        return ExportService(
            snapshot.paths,
            self._cache,
            self._source,
            self._writer,
            tts_settings=snapshot.tts_runtime(),
        )

    def export_tsv(
        self,
        output_path: Path,
        language: str,
        deck_name: str | None = None,
        *,
        snapshot: ExportSnapshot | None = None,
    ) -> int:
        with diagnostic_operation("export") as diagnostic:
            del deck_name
            prepared = self._resolve_snapshot(language, snapshot)
            entries = prepared.entries()
            exported = self._writer.export_tsv(output_path, entries)
            diagnostic.finish("empty" if not exported else "success", row_count=exported)
            return exported

    def count_entries(
        self,
        language: str,
        *,
        snapshot: ExportSnapshot | None = None,
    ) -> int:
        return self._resolve_snapshot(language, snapshot).count

    def export_apkg(
        self,
        output_path: Path,
        deck_name: str,
        language: str,
        progress_callback=None,
        *,
        snapshot: ExportSnapshot | None = None,
    ) -> int:
        with diagnostic_operation("export") as diagnostic:
            prepared = self._resolve_snapshot(language, snapshot)
            entries = prepared.entries()
            exported = self._writer.export_apkg(
                output_path,
                entries,
                deck_name,
                settings=self._tts_settings,
                progress_callback=progress_callback,
            )
            diagnostic.finish("empty" if not exported else "success", row_count=exported)
            return exported

    def prepare_snapshot(self, language: str) -> ExportSnapshot:
        path = self._excel_path(language)
        if path is None:
            return ExportSnapshot(language, None, None, ())
        try:
            prepare_source = getattr(self._source, "prepare_snapshot", None)
            if callable(prepare_source):
                source_snapshot = prepare_source(path, language)
                rows = tuple(source_snapshot.rows)
                revision = source_snapshot.revision
            else:
                rows = tuple(self._source.read_rows(path, language))
                revision = WorkbookRevision.capture(path)
            flat_entries = [_entry_from_flat_row(row.data) for row in rows]
            get_many = getattr(self._cache, "get_many", None)
            if callable(get_many):
                cached_entries = get_many(
                    [(entry.word, language) for entry in flat_entries],
                    workbook_path=path,
                    refs=[row.ref for row in rows],
                )
            else:
                cached_entries = [
                    self._cache.get_saved_projection(path, row.ref)
                    or self._cache.get(entry.word, language)
                    for row, entry in zip(rows, flat_entries)
                ]
            if len(cached_entries) != len(rows):
                raise RuntimeError("cache batch result length mismatch")
            entries = tuple(
                entry_from_export_row(
                    row.data,
                    cached,
                    _base=flat,
                ).to_json()
                for row, flat, cached in zip(
                    rows,
                    flat_entries,
                    cached_entries,
                )
            )
            return ExportSnapshot(language, path, revision, entries)
        except Exception as exc:
            if isinstance(exc, ExportPreparationError):
                raise
            raise ExportPreparationError(path, exc) from exc

    def _collect_entries(self, language: str) -> list[VocabularyEntry]:
        """Compatibility facade for older callers and tests."""
        return self.prepare_snapshot(language).entries()

    def _resolve_snapshot(
        self,
        language: str,
        snapshot: ExportSnapshot | None,
    ) -> ExportSnapshot:
        if snapshot is None:
            return self.prepare_snapshot(language)
        if snapshot.language != language:
            raise ValueError("export snapshot language mismatch")
        return snapshot

    def _excel_path(self, language: str) -> Path | None:
        path_str = self._paths.excel_path_for(language)
        return Path(path_str).expanduser() if path_str else None


def _entry_from_flat_row(data: dict) -> VocabularyEntry:
    entry = row_data_to_entry(
        data,
        parse_meanings_detail=True,
        preserve_blank_translations=True,
    )
    if not entry.meanings_summary:
        entry.meanings_summary = build_meanings_summary(entry)
    return entry


def entry_from_export_row(
    data: dict,
    cached: VocabularyEntry | None = None,
    *,
    _base: VocabularyEntry | None = None,
) -> VocabularyEntry:
    """Build an export entry with Excel as the editable source of truth.

    The cache is allowed to restore rich nested meaning/example structure,
    but it must not overwrite cells the user can edit in Excel. To avoid
    exporting stale definitions after a spreadsheet edit, cached meaning
    groups are reused only when the visible summary still matches.
    """
    base = _base or _entry_from_flat_row(data)
    if cached is None:
        return base

    has_meanings_detail_column = "meanings_detail" in data
    cached_summary = cached.meanings_summary or build_meanings_summary(cached)
    base_summary = str(data.get("meanings_summary", "") or base.meanings_summary or "")
    if (
        not has_meanings_detail_column
        and cached.meaning_groups
        and (not base_summary or base_summary == cached_summary)
    ):
        base.meaning_groups = deepcopy(cached.meaning_groups)
        if base.examples_flat:
            replace_nested_examples(base.meaning_groups, base.examples_flat)
        if not base.meanings_summary:
            base.meanings_summary = cached_summary

    if not base.examples_flat and cached.examples_flat:
        base.examples_flat = deepcopy(cached.examples_flat)
        for group in base.meaning_groups:
            for sense in group.senses:
                for sub in sense.sub_senses:
                    if not sub.examples:
                        sub.examples = deepcopy(cached.examples_flat)

    base.source_provider = "excel"
    return base
