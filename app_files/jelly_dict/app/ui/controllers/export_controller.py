"""Anki TSV / APKG export flow.

Extracted from MainWindow as a small delegate. Behavior is identical
to the previous inline implementation: same file dialog default paths,
same deck name format, same message strings.

Heavy work (genanki APKG generation, Excel scan) runs on a QThread so
the window doesn't freeze on large decks. The user still sees the same
final completion / failure dialogs.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.services.export_preflight import run_export_preflight
from app.services.export_service import ExportService
from app.storage.settings_store import Settings, SettingsStore
from app.ui.export_options import (
    AudioPolicy,
    ExportPlan,
    apply_audio_policy,
    build_export_plan,
    should_confirm_export,
)
from app.ui.export_options_dialog import ExportOptionsDialog
from app.ui.export_worker import ExportWorker


class ExportController(QtCore.QObject):
    settingsRequested = QtCore.Signal()

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        settings: Settings,
        export_service: ExportService,
        settings_store: SettingsStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._settings = settings
        self._export_service = export_service
        self._settings_store = settings_store
        # Holds the active thread so it isn't garbage-collected mid-run.
        self._active_thread: QtCore.QThread | None = None
        self._active_worker: ExportWorker | None = None
        self._busy_dialog: QtWidgets.QProgressDialog | None = None
        self._success_title = ""
        self._success_path: Path | None = None
        self._success_plan: ExportPlan | None = None

    def update_settings(
        self, settings: Settings, export_service: ExportService | None = None
    ) -> None:
        self._settings = settings
        if export_service is not None:
            self._export_service = export_service

    def close(self) -> None:
        if self._active_thread is not None and self._active_thread.isRunning():
            self._active_thread.quit()
            self._active_thread.wait(2000)
        if self._busy_dialog is not None:
            self._busy_dialog.close()

    def is_running(self) -> bool:
        if self._active_thread is None:
            return False
        try:
            return self._active_thread.isRunning()
        except RuntimeError:
            self._clear_active()
            return False

    # ---------- public entry points -----------------------------------

    def export_tsv(self, language: str) -> None:
        default = (
            Path(self._settings.anki_path_for(language))
            .expanduser()
            .with_suffix(".tsv")
        )
        path_str, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._parent,
            f"Anki TSV 저장 ({language})",
            str(default),
            "TSV (*.tsv)",
        )
        if not path_str:
            return
        self._run_async(
            kind="tsv",
            output_path=Path(path_str),
            language=language,
            success_title="Anki TSV",
        )

    def export_apkg(
        self,
        language: str,
        audio_policy: AudioPolicy = "settings",
        force_options: bool = False,
    ) -> None:
        default = Path(self._settings.anki_path_for(language)).expanduser()
        path_str, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._parent,
            f"Anki APKG 저장 ({language})",
            str(default),
            "APKG (*.apkg)",
        )
        if not path_str:
            return
        deck_name = f"{self._settings.default_deck_name}::{language.upper()}"
        output_path = Path(path_str)
        try:
            count = self._export_service.count_entries(language)
        except Exception:
            count = 0
        plan = build_export_plan(
            self._settings,
            language=language,
            deck_name=deck_name,
            card_count=count,
            audio_policy=audio_policy,
        )
        effective_settings = apply_audio_policy(deepcopy(self._settings), language, audio_policy)
        preflight = run_export_preflight(effective_settings, plan, output_path=output_path)
        should_confirm = force_options or should_confirm_export(
            self._settings,
            plan,
            has_blockers=bool(preflight.blockers),
            has_warnings=bool(preflight.warnings),
            output_exists=output_path.exists(),
        )
        if should_confirm:
            dlg = ExportOptionsDialog(
                plan=plan,
                output_path=output_path,
                preflight=preflight,
                force_options=force_options,
                parent=self._parent,
            )
            result = dlg.exec()
            if result == 2:
                self.settingsRequested.emit()
                return
            if result != QtWidgets.QDialog.Accepted:
                return
            selected = dlg.selected_options()
            audio_policy = selected.audio_policy
            plan = build_export_plan(
                self._settings,
                language=language,
                deck_name=deck_name,
                card_count=count,
                audio_policy=audio_policy,
            )
            effective_settings = apply_audio_policy(deepcopy(self._settings), language, audio_policy)
            preflight = run_export_preflight(effective_settings, plan, output_path=output_path)
            if preflight.blockers:
                QtWidgets.QMessageBox.warning(
                    self._parent,
                    "내보내기 불가",
                    "\n".join(issue.message for issue in preflight.blockers),
                )
                return
            if selected.suppress_future_confirm:
                self._settings.anki_export_confirm_mode = "never"
            if selected.save_as_default:
                self._settings = apply_audio_policy(self._settings, language, audio_policy)
            if selected.suppress_future_confirm or selected.save_as_default:
                self._save_settings()

        export_service = ExportService(effective_settings, self._export_service.cache)
        self._run_async(
            kind="apkg",
            output_path=output_path,
            language=language,
            success_title="Anki APKG",
            deck_name=deck_name,
            service=export_service,
            plan=plan,
        )

    # ---------- internal ----------------------------------------------

    def _run_async(
        self,
        *,
        kind: str,
        output_path: Path,
        language: str,
        success_title: str,
        deck_name: str | None = None,
        service: ExportService | None = None,
        plan: ExportPlan | None = None,
    ) -> None:
        # Show an indeterminate progress dialog so the user sees the app
        # is working. Cancel button does not interrupt the genanki call
        # (the underlying library is synchronous), but the UI returns
        # control as soon as the worker finishes.
        initial_label = (
            f"Anki APKG 생성 중… ({language})"
            if kind == "apkg"
            else f"내보내는 중… ({language})"
        )
        progress = QtWidgets.QProgressDialog(
            initial_label,
            None,  # no cancel — would leave a half-written file
            0, 0,  # range gets switched to (0, total) on first progress emit
            self._parent,
        )
        progress.setWindowTitle(success_title)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        self._success_title = success_title
        self._busy_dialog = progress
        self._success_path = output_path
        self._success_plan = plan

        thread = QtCore.QThread(self)
        worker = ExportWorker(
            service or self._export_service,
            kind,  # type: ignore[arg-type]
            output_path,
            language,
            deck_name,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        if hasattr(worker, "progress"):
            worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_active)

        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _on_export_progress(self, current: int, total: int, word: str) -> None:
        if self._busy_dialog is None:
            return
        # Switch from indeterminate to determinate the first time we see
        # a real total. Truncate the displayed word so the dialog doesn't
        # grow horizontally.
        if self._busy_dialog.maximum() != total:
            self._busy_dialog.setRange(0, total)
        self._busy_dialog.setValue(current)
        shown = (word[:18] + "…") if len(word) > 18 else word
        pct = int(current * 100 / total) if total else 0
        if self._success_plan is not None and self._success_plan.effective_tts_enabled:
            detail = f"TTS 생성/카드 처리: {shown}"
        else:
            detail = f"카드 처리: {shown}"
        self._busy_dialog.setLabelText(
            f"Anki APKG 생성 중… {current} / {total}  ({pct}%)\n{detail}"
        )

    @QtCore.Slot(int)
    def _on_finished(self, count: int) -> None:
        if self._busy_dialog is not None:
            self._busy_dialog.close()
        detail = f"{count}개 카드 내보냄"
        if self._success_plan is not None:
            detail += f" · {self._success_plan.audio_summary}"
        if self._success_plan is not None and self._success_plan.audio_policy == "remove_audio":
            detail += "\n\n기존 Anki 카드에서 음성을 제거하려면 가져오기 시 기존 노트 업데이트를 선택하세요."
        msg = QtWidgets.QMessageBox(self._parent)
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setWindowTitle(self._success_title)
        msg.setText(detail)
        ok_btn = msg.addButton("확인", QtWidgets.QMessageBox.AcceptRole)
        finder_btn = msg.addButton("Finder에서 보기", QtWidgets.QMessageBox.ActionRole)
        msg.exec()
        if msg.clickedButton() is finder_btn and self._success_path is not None:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self._success_path.parent))
            )
        if self._success_plan is not None:
            self._settings.last_apkg_export_tts_enabled = self._success_plan.effective_tts_enabled
            self._settings.last_apkg_export_audio_policy = self._success_plan.audio_policy
            self._save_settings()
        del ok_btn

    def _save_settings(self) -> None:
        if self._settings_store is None:
            return
        try:
            self._settings_store.save(self._settings)
        except Exception:
            pass

    @QtCore.Slot(str)
    def _on_failed(self, message: str) -> None:
        if self._busy_dialog is not None:
            self._busy_dialog.close()
        QtWidgets.QMessageBox.warning(self._parent, "내보내기 실패", message)

    @QtCore.Slot()
    def _clear_active(self) -> None:
        self._active_thread = None
        self._active_worker = None
        self._busy_dialog = None
