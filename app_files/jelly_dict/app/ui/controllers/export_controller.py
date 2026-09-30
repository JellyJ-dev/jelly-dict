"""Anki TSV / APKG export flow.

Extracted from MainWindow as a small delegate. Behavior is identical
to the previous inline implementation: same file dialog default paths,
same deck name format, same message strings.

Heavy work (genanki APKG generation, Excel scan) runs on a QThread so
the window doesn't freeze on large decks. The user still sees the same
final completion / failure dialogs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.core.settings import AppSettings, SettingsDraft, settings_snapshot
from app.services.export_service import (
    ExportService,
    ExportSnapshot,
)
from app.services.ports import ExportCapabilitiesPort
from app.storage.settings_store import SettingsStore
from app.ui.async_task import (
    SignalBinding,
    TaskSupervisor,
    TaskTerminal,
    TerminalBinding,
)
from app.ui.export_options import (
    AudioPolicy,
    ExportPlan,
    apply_audio_policy,
    should_confirm_export,
)
from app.ui.export_options_dialog import ExportOptionsDialog
from app.ui.export_worker import (
    ExportPreparationResult,
    ExportPreparationWorker,
    ExportWorker,
)


@dataclass(frozen=True)
class _ApkgRequest:
    language: str
    audio_policy: AudioPolicy
    force_options: bool
    output_path: Path
    deck_name: str
    service: ExportService
    settings: AppSettings
    confirmed: bool = False
    save_as_default: bool = False
    suppress_future_confirm: bool = False


class ExportController(QtCore.QObject):
    settingsRequested = QtCore.Signal()

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        settings: AppSettings | SettingsDraft,
        export_service: ExportService,
        capabilities: ExportCapabilitiesPort,
        settings_store: SettingsStore | None = None,
        settings_applier: Callable[[AppSettings], object] | None = None,
        settings_committer: Callable[[AppSettings], object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._settings = settings_snapshot(settings)
        self._export_service = export_service
        self._capabilities = capabilities
        self._settings_store = settings_store
        self._settings_applier = settings_applier
        self._settings_committer = settings_committer
        self._task = TaskSupervisor(self, name="export")
        self._prepare_task = TaskSupervisor(self, name="export-prepare")
        self._task.terminal.connect(self._on_task_terminal)
        self._prepare_task.terminal.connect(self._on_prepare_task_terminal)
        self._busy_dialog: QtWidgets.QProgressDialog | None = None
        self._success_title = ""
        self._success_path: Path | None = None
        self._success_plan: ExportPlan | None = None
        self._active_request: _ApkgRequest | None = None
        self._pending_preparation: tuple[_ApkgRequest, ExportSnapshot | None] | None = None

    def update_settings(
        self,
        settings: AppSettings | SettingsDraft,
        export_service: ExportService | None = None,
    ) -> None:
        self._settings = settings_snapshot(settings)
        if export_service is not None:
            self._export_service = export_service

    def close(self) -> bool:
        prepared = self._prepare_task.close()
        stopped = self._task.close()
        if stopped and self._busy_dialog is not None:
            self._busy_dialog.close()
        return prepared and stopped

    def is_running(self) -> bool:
        return self._prepare_task.is_running() or self._task.is_running()

    # ---------- public entry points -----------------------------------

    def export_tsv(self, language: str) -> None:
        if self.is_running():
            return
        default = Path(self._settings.anki_path_for(language)).expanduser().with_suffix(".tsv")
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
        if self.is_running():
            return
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
        request = _ApkgRequest(
            language,
            audio_policy,
            force_options,
            output_path,
            deck_name,
            self._export_service,
            self._settings,
        )
        self._active_request = request
        self._start_preparation(request)

    def _start_preparation(
        self,
        request: _ApkgRequest,
        snapshot: ExportSnapshot | None = None,
    ) -> None:
        worker = ExportPreparationWorker(
            request.service,
            request.settings,
            self._capabilities,
            language=request.language,
            deck_name=request.deck_name,
            output_path=request.output_path,
            audio_policy=request.audio_policy,
            snapshot=snapshot,
        )
        self._prepare_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_preparation_finished,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_preparation_failed,
                ),
            ],
        )

    @QtCore.Slot(object)
    def _on_preparation_finished(self, result_obj: object) -> None:
        request = self._active_request
        if request is None or not isinstance(result_obj, ExportPreparationResult):
            self._on_preparation_failed("내보내기 준비 결과가 올바르지 않습니다.")
            return
        plan = result_obj.plan
        preflight = result_obj.preflight
        should_confirm = request.force_options or should_confirm_export(
            request.settings,
            plan,
            has_blockers=bool(preflight.blockers),
            has_warnings=bool(preflight.warnings),
            output_exists=request.output_path.exists(),
        )
        if should_confirm and not request.confirmed:
            dlg = ExportOptionsDialog(
                plan=plan,
                output_path=request.output_path,
                preflight=preflight,
                force_options=request.force_options,
                parent=self._parent,
            )
            result = dlg.exec()
            if result == 2:
                self._active_request = None
                self.settingsRequested.emit()
                return
            if result != QtWidgets.QDialog.Accepted:
                self._active_request = None
                return
            selected = dlg.selected_options()
            confirmed = replace(
                request,
                audio_policy=selected.audio_policy,
                confirmed=True,
                save_as_default=selected.save_as_default,
                suppress_future_confirm=selected.suppress_future_confirm,
            )
            self._active_request = confirmed
            self._pending_preparation = (confirmed, result_obj.snapshot)
            return

        if request.confirmed and preflight.blockers:
            QtWidgets.QMessageBox.warning(
                self._parent,
                "내보내기 불가",
                "\n".join(issue.message for issue in preflight.blockers),
            )
            self._active_request = None
            return
        candidate_settings = self._settings
        if request.suppress_future_confirm:
            candidate_settings = candidate_settings.with_changes(anki_export_confirm_mode="never")
        if request.save_as_default:
            candidate_settings = apply_audio_policy(
                candidate_settings,
                request.language,
                request.audio_policy,
            )
        if request.suppress_future_confirm or request.save_as_default:
            self._save_settings(candidate_settings)

        export_service = request.service.with_settings(result_obj.effective_settings)
        self._run_async(
            kind="apkg",
            output_path=request.output_path,
            language=request.language,
            success_title="Anki APKG",
            deck_name=request.deck_name,
            service=export_service,
            plan=plan,
            snapshot=result_obj.snapshot,
        )

    @QtCore.Slot(str)
    def _on_preparation_failed(self, message: str) -> None:
        self._active_request = None
        self._pending_preparation = None
        QtWidgets.QMessageBox.warning(self._parent, "내보내기 실패", message)

    @QtCore.Slot(object)
    def _on_prepare_task_terminal(self, _outcome: object) -> None:
        pending = self._pending_preparation
        self._pending_preparation = None
        if pending is not None:
            self._start_preparation(*pending)

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
        snapshot: ExportSnapshot | None = None,
    ) -> None:
        # Show an indeterminate progress dialog so the user sees the app
        # is working. Cancel button does not interrupt the genanki call
        # (the underlying library is synchronous), but the UI returns
        # control as soon as the worker finishes.
        initial_label = (
            f"Anki APKG 생성 중… ({language})" if kind == "apkg" else f"내보내는 중… ({language})"
        )
        progress = QtWidgets.QProgressDialog(
            initial_label,
            None,  # no cancel — would leave a half-written file
            0,
            0,  # range gets switched to (0, total) on first progress emit
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

        worker = ExportWorker(
            service or self._export_service,
            kind,  # type: ignore[arg-type]
            output_path,
            language,
            deck_name,
            snapshot,
        )
        progress_bindings = []
        if hasattr(worker, "progress"):
            progress_bindings.append(SignalBinding(worker.progress, self._on_export_progress))
        self._task.start(
            worker,
            run=worker.run,
            signal_bindings=progress_bindings,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_finished,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_failed,
                ),
            ],
        )

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
            candidate = self._settings.with_changes(
                last_apkg_export_tts_enabled=(self._success_plan.effective_tts_enabled),
                last_apkg_export_audio_policy=self._success_plan.audio_policy,
            )
            self._save_settings(candidate)
        del ok_btn

    def _save_settings(self, candidate: AppSettings) -> bool:
        if self._settings_committer is not None:
            try:
                self._settings_committer(candidate)
            except Exception:
                return False
            self._settings = candidate
            return True
        if self._settings_store is None:
            self._settings = candidate
            return True
        try:
            self._settings_store.save(candidate)
        except Exception:
            return False
        self._settings = candidate
        if self._settings_applier is not None:
            self._settings_applier(candidate)
        return True

    @QtCore.Slot(str)
    def _on_failed(self, message: str) -> None:
        if self._busy_dialog is not None:
            self._busy_dialog.close()
        QtWidgets.QMessageBox.warning(self._parent, "내보내기 실패", message)

    @QtCore.Slot()
    def _clear_active(self) -> None:
        self._busy_dialog = None

    @QtCore.Slot(object)
    def _on_task_terminal(self, _outcome: object) -> None:
        self._active_request = None
        self._clear_active()
