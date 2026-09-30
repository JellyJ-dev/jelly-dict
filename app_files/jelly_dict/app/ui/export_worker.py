"""Background worker for Anki TSV/APKG exports.

Keeping the export off the UI thread avoids freezing the window when
the workbook is large or genanki has to write hundreds of cards.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6 import QtCore

from app.core.export_plan import AudioPolicy, ExportPlan
from app.core.settings import AppSettings, SettingsDraft
from app.services.export_preflight import PreflightResult, run_export_preflight
from app.services.export_service import ExportService, ExportSnapshot
from app.services.ports import ExportCapabilitiesPort
from app.ui.export_options import apply_audio_policy, build_export_plan

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportPreparationResult:
    snapshot: ExportSnapshot
    plan: ExportPlan
    effective_settings: AppSettings
    preflight: PreflightResult


class ExportPreparationWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        service: ExportService,
        settings: AppSettings | SettingsDraft,
        capabilities: ExportCapabilitiesPort,
        *,
        language: str,
        deck_name: str,
        output_path: Path,
        audio_policy: AudioPolicy,
        snapshot: ExportSnapshot | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._settings = settings
        self._capabilities = capabilities
        self._language = language
        self._deck_name = deck_name
        self._output_path = output_path
        self._audio_policy = audio_policy
        self._snapshot = snapshot

    @QtCore.Slot()
    def run(self) -> None:
        try:
            snapshot = self._snapshot or self._service.prepare_snapshot(self._language)
            plan = build_export_plan(
                self._settings,
                language=self._language,
                deck_name=self._deck_name,
                card_count=snapshot.count,
                audio_policy=self._audio_policy,
            )
            effective = apply_audio_policy(
                self._settings,
                self._language,
                self._audio_policy,
            )
            preflight = run_export_preflight(
                effective,
                plan,
                output_path=self._output_path,
                capabilities=self._capabilities,
            )
        except Exception as exc:
            log.exception("export preparation failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(ExportPreparationResult(snapshot, plan, effective, preflight))


class ExportWorker(QtCore.QObject):
    finished = QtCore.Signal(int)  # written count
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(int, int, str)  # current, total, current_word

    def __init__(
        self,
        service: ExportService,
        kind: Literal["tsv", "apkg"],
        output_path: Path,
        language: str,
        deck_name: str | None = None,
        snapshot: ExportSnapshot | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._kind = kind
        self._output_path = output_path
        self._language = language
        self._deck_name = deck_name
        self._snapshot = snapshot

    @QtCore.Slot()
    def run(self) -> None:
        try:
            if self._kind == "tsv":
                count = self._service.export_tsv(
                    self._output_path,
                    language=self._language,
                    snapshot=self._snapshot,
                )
            else:
                count = self._service.export_apkg(
                    self._output_path,
                    deck_name=self._deck_name or "JellyDict",
                    language=self._language,
                    progress_callback=self._emit_progress,
                    snapshot=self._snapshot,
                )
        except Exception as exc:  # pragma: no cover - safety net
            log.exception("export worker crashed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(count)

    def _emit_progress(self, current: int, total: int, word: str) -> None:
        # Qt signal across threads — automatically queued to UI thread.
        self.progress.emit(current, total, word)
