from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.core.settings import AppSettings, SettingsDraft
from app.storage import secret_store
from app.ui.async_task import TaskSupervisor, TaskTerminal, TerminalBinding
from app.ui.settings_contract import (
    EDGE_TTS_INSTALL_HINT,
    SAMPLE_TEXT_EN,
    SAMPLE_TEXT_JA,
    VOICEVOX_DOWNLOAD_URL,
)
from app.ui.settings_ui_refs import SettingsUiRefs
from app.ui.settings_widgets import _VoicevoxVoicePicker, set_status_state
from app.ui.settings_workers import (
    _AnkiConnectTestWorker,
    _GoogleVisionKeyTestWorker,
    _SampleSynthWorker,
    _SettingsStatusWorker,
)


class _SettingsRuntime:
    """Shared state context; every widget access goes through SettingsUiRefs."""

    def __init__(
        self,
        dialog: QtWidgets.QDialog,
        ui: SettingsUiRefs,
        draft: SettingsDraft,
        store,
        settings_commit,
    ) -> None:
        self.dialog = dialog
        self.ui = ui
        self._draft = draft
        self._store = store
        self._settings_commit = settings_commit
        self._sample_player = None
        self._install_thread: QtCore.QThread | None = None
        self._sample_thread: QtCore.QThread | None = None
        self._network_test_thread: QtCore.QThread | None = None
        self._network_test_worker: QtCore.QObject | None = None
        self._status_thread: QtCore.QThread | None = None
        self._status_worker: _SettingsStatusWorker | None = None
        self._sample_task = TaskSupervisor(dialog, name="settings-tts-sample")
        self._network_test_task = TaskSupervisor(dialog, name="settings-network-test")
        self._status_task = TaskSupervisor(dialog, name="settings-status-probe")
        self._network_test_task.terminal.connect(self._on_network_task_terminal)
        self._status_task.terminal.connect(self._on_status_task_terminal)
        self._status_probe_timer = QtCore.QTimer(dialog)
        self._status_probe_timer.setSingleShot(True)
        self._status_probe_timer.timeout.connect(self._start_status_probe)

    # ── engine combos ──────────────────────────────────────────────
    def _populate_engine_combo(self, combo: QtWidgets.QComboBox, language: str) -> None:
        from app.providers import get_provider_registry

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("사용 안 함", "none")
        registry = get_provider_registry()
        for descriptor in registry.descriptors("tts", settings_only=True):
            capability = descriptor.capabilities(self._draft)
            voices = capability.voices_for(language)
            if not voices:
                continue
            label = descriptor.display_name
            if capability.availability_for(language) == "missing":
                label = f"{label} (미설치)"
            combo.addItem(label, descriptor.id)
        combo.blockSignals(False)

    def _refresh_voices(self, language: str) -> None:
        if language == "en":
            engine_combo = self.ui.tts_engine_en_combo
            voice_combo = self.ui.tts_voice_en_combo
        else:
            engine_combo = self.ui.tts_engine_ja_combo
            voice_combo = self.ui.tts_voice_ja_combo
        name = engine_combo.currentData()
        voice_combo.blockSignals(True)
        voice_combo.clear()
        if name and name != "none":
            voices = self._voices_for(name, language)
            for v in voices:
                voice_combo.addItem(self._voice_display_label(name, v), v)
        voice_combo.blockSignals(False)
        self._refresh_license_label()

    def _voice_display_label(self, engine: str, voice: str) -> str:
        if engine == "voicevox":
            from app.anki.tts.voicevox_provider import display_label

            return display_label(voice)
        return voice

    def _refresh_voice_add_visibility(self) -> None:
        """Show the '+' picker only when VOICEVOX is the JA engine."""
        is_voicevox = self.ui.tts_engine_ja_combo.currentData() == "voicevox"
        self.ui.tts_voice_add_btn.setVisible(is_voicevox)

    def _open_voicevox_picker(self) -> None:
        from app.anki.tts.voicevox_provider import VoicevoxProvider

        if not VoicevoxProvider.is_running():
            self.ui.tts_license_label.setText(
                "VOICEVOX 엔진이 가동 중이 아닙니다. 앱을 실행한 뒤 다시 시도하세요."
            )
            return

        all_voices = VoicevoxProvider.fetch_voices(self._draft.voicevox_url)
        if not all_voices:
            self.ui.tts_license_label.setText("VOICEVOX 음성 목록을 불러오지 못했습니다.")
            return

        current = set(self._draft.tts_voicevox_voices)
        dlg = _VoicevoxVoicePicker(all_voices, current, self.dialog)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        chosen = dlg.selected()
        if not chosen:
            return
        self._draft.tts_voicevox_voices = list(chosen)
        self._refresh_voices("ja")

    def _voices_for(self, engine: str, language: str) -> tuple[str, ...]:
        """Per-engine voice list — for VOICEVOX, return the user's saved
        curated list (defaults to the 5 standard voices). The "+" button
        lets the user pull from the live engine catalog."""
        from app.providers import get_provider_registry

        if engine == "voicevox" and language == "ja":
            return tuple(self._draft.tts_voicevox_voices) or ()
        capability = get_provider_registry().capabilities(
            "tts",
            engine,
            self._draft,
        )
        return capability.voices_for(language)

    def _refresh_license_label(self) -> None:
        from app.anki.tts import get_provider_info

        notes: list[str] = []
        for combo, lang in (
            (self.ui.tts_engine_en_combo, "EN"),
            (self.ui.tts_engine_ja_combo, "JA"),
        ):
            name = combo.currentData()
            if not name or name == "none":
                continue
            info = get_provider_info(name)
            line = f"{lang} {info.display_name} — {info.license_note}"
            if info.usage_warning:
                line += f"  ⚠ {info.usage_warning}"
            notes.append(line)
        self.ui.tts_license_label.setText("\n".join(notes))

    def _refresh_install_status(self) -> None:
        from app.anki.tts import get_provider_info
        from app.ui.tts_install_worker import (
            brew_available,
            kokoro_model_cache_size,
        )

        kokoro = get_provider_info("kokoro")
        edge = get_provider_info("edge")
        self._apply_install_status(
            kokoro_available=kokoro.available,
            edge_available=edge.available,
            brew_is_available=brew_available(),
            kokoro_cache_mb=kokoro_model_cache_size() / 1024 / 1024,
        )

    def _apply_install_status(
        self,
        *,
        kokoro_available: bool,
        edge_available: bool,
        brew_is_available: bool,
        kokoro_cache_mb: float,
    ) -> None:
        if kokoro_available:
            self.ui.tts_install_btn.setEnabled(False)
            self.ui.tts_install_btn.setText("Kokoro ✓")
            self.ui.kokoro_uninstall_btn.show()
            if kokoro_cache_mb > 1:
                self.ui.kokoro_uninstall_btn.setToolTip(
                    f"Kokoro 삭제 — 패키지 + 모델 캐시(~{kokoro_cache_mb:.0f}MB) 정리"
                )
        else:
            self.ui.tts_install_btn.setEnabled(True)
            self.ui.tts_install_btn.setText("Kokoro 설치")
            self.ui.kokoro_uninstall_btn.hide()

        # VOICEVOX never runs through brew (no cask exists) — always
        # surfaces the download page, so be upfront about it.
        self.ui.voicevox_install_btn.setText("VOICEVOX 다운로드")
        # We can't reliably tell whether VOICEVOX is installed (it could
        # be a brew cask, a manual /Applications drop, or absent), so the
        # uninstall button is always available when brew is around — its
        # worker reports gracefully if there's nothing to uninstall.
        self.ui.voicevox_uninstall_btn.setVisible(brew_is_available)

        if edge_available:
            self.ui.edge_install_btn.setEnabled(False)
            self.ui.edge_install_btn.setText("edge-tts ✓")
            self.ui.edge_uninstall_btn.show()
        else:
            self.ui.edge_install_btn.setEnabled(True)
            self.ui.edge_install_btn.setText("edge-tts 설치")
            self.ui.edge_uninstall_btn.hide()
        self.ui.tts_install_status.setText("")

    # ── load / save ────────────────────────────────────────────────
    def _load(self, settings: AppSettings | SettingsDraft) -> None:
        self.ui.excel_dir.set_path(settings.default_excel_dir)
        self.ui.excel_en.set_path(settings.excel_path_en or settings.excel_path_for("en"))
        self.ui.excel_ja.set_path(settings.excel_path_ja or settings.excel_path_for("ja"))
        self.ui.anki_dir.set_path(settings.default_anki_export_dir)
        self.ui.anki_en.set_path(settings.anki_path_en or settings.anki_path_for("en"))
        self.ui.anki_ja.set_path(settings.anki_path_ja or settings.anki_path_for("ja"))
        self.ui.delay.setValue(settings.request_delay_seconds)
        self.ui.cache_check.setChecked(settings.cache_enabled)
        self.ui.preview_check.setChecked(settings.show_preview)
        idx = self.ui.dup_combo.findData(settings.duplicate_policy)
        if idx >= 0:
            self.ui.dup_combo.setCurrentIndex(idx)
        self.ui.deck_name.setText(settings.default_deck_name)
        idx = self.ui.provider_combo.findData(settings.provider)
        if idx >= 0:
            self.ui.provider_combo.setCurrentIndex(idx)
        self.ui.ankiconnect_check.setChecked(settings.ankiconnect_enabled)
        self.ui.ankiconnect_url.setText(settings.ankiconnect_url)

        idx = self.ui.ocr_combo.findData(getattr(settings, "ocr_provider", "apple_vision"))
        if idx >= 0:
            self.ui.ocr_combo.setCurrentIndex(idx)
        set_status_state(self.ui.gv_key_status, "muted")
        self.ui.gv_key_status.setText("키 상태 확인 중…")

        self.ui.tts_enabled_check.setChecked(settings.tts_enabled)
        self.ui.tts_play_front_check.setChecked(settings.tts_play_front)
        self.ui.tts_play_back_check.setChecked(settings.tts_play_back)
        self.ui.tts_play_examples_check.setChecked(settings.tts_play_examples)
        self.ui.tts_pre_generate_check.setChecked(settings.tts_pre_generate_on_save)

        self._populate_engine_combo(self.ui.tts_engine_en_combo, "en")
        self._populate_engine_combo(self.ui.tts_engine_ja_combo, "ja")
        idx = self.ui.tts_engine_en_combo.findData(settings.tts_engine_en)
        if idx >= 0:
            self.ui.tts_engine_en_combo.setCurrentIndex(idx)
        idx = self.ui.tts_engine_ja_combo.findData(settings.tts_engine_ja)
        if idx >= 0:
            self.ui.tts_engine_ja_combo.setCurrentIndex(idx)
        self._refresh_voices("en")
        self._refresh_voices("ja")
        idx = self.ui.tts_voice_en_combo.findData(settings.tts_voice_en)
        if idx >= 0:
            self.ui.tts_voice_en_combo.setCurrentIndex(idx)
        idx = self.ui.tts_voice_ja_combo.findData(settings.tts_voice_ja)
        if idx >= 0:
            self.ui.tts_voice_ja_combo.setCurrentIndex(idx)
        self.ui.tts_install_status.setText("설치 상태 확인 중…")
        self._refresh_voice_add_visibility()

    def _start_status_probe(self) -> None:
        if self._status_task.is_running():
            return
        worker = _SettingsStatusWorker()
        self._status_worker = worker
        self._status_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_status_probe_finished,
                )
            ],
        )

    @QtCore.Slot(object)
    def _on_status_probe_finished(self, status_obj: object) -> None:
        status = status_obj if isinstance(status_obj, dict) else {}
        self._apply_gv_key_status(bool(status.get("gv_key_set", False)))
        self._apply_install_status(
            kokoro_available=bool(status.get("kokoro_available", False)),
            edge_available=bool(status.get("edge_available", False)),
            brew_is_available=bool(status.get("brew_available", False)),
            kokoro_cache_mb=float(status.get("kokoro_cache_mb", 0.0) or 0.0),
        )

    @QtCore.Slot()
    def _clear_status_probe(self) -> None:
        self._status_thread = None
        self._status_worker = None

    @QtCore.Slot(object)
    def _on_status_task_terminal(self, _outcome: object) -> None:
        self._clear_status_probe()

    def _save(self) -> None:
        if not self._ready_for_close_or_save():
            return
        en_engine = self.ui.tts_engine_en_combo.currentData() or "none"
        ja_engine = self.ui.tts_engine_ja_combo.currentData() or "none"
        en_voice = self.ui.tts_voice_en_combo.currentData() or ""
        ja_voice = self.ui.tts_voice_ja_combo.currentData() or ""
        draft = deepcopy(self._draft)
        draft.default_excel_dir = self.ui.excel_dir.path() or ""
        draft.excel_path_en = self.ui.excel_en.path() or ""
        draft.excel_path_ja = self.ui.excel_ja.path() or ""
        draft.default_anki_export_dir = self.ui.anki_dir.path() or ""
        draft.anki_path_en = self.ui.anki_en.path() or ""
        draft.anki_path_ja = self.ui.anki_ja.path() or ""
        draft.request_delay_seconds = float(self.ui.delay.value())
        draft.cache_enabled = self.ui.cache_check.isChecked()
        draft.show_preview = self.ui.preview_check.isChecked()
        draft.duplicate_policy = self.ui.dup_combo.currentData()
        draft.default_deck_name = self.ui.deck_name.text().strip() or "JellyDict"
        draft.provider = self.ui.provider_combo.currentData()
        draft.ankiconnect_enabled = self.ui.ankiconnect_check.isChecked()
        draft.ankiconnect_url = self.ui.ankiconnect_url.text().strip() or "http://127.0.0.1:8765"
        draft.ocr_provider = self.ui.ocr_combo.currentData() or "apple_vision"
        draft.tts_enabled = self.ui.tts_enabled_check.isChecked()
        draft.tts_play_front = self.ui.tts_play_front_check.isChecked()
        draft.tts_play_back = self.ui.tts_play_back_check.isChecked()
        draft.tts_play_examples = self.ui.tts_play_examples_check.isChecked()
        draft.tts_pre_generate_on_save = self.ui.tts_pre_generate_check.isChecked()
        draft.tts_engine_en = en_engine
        draft.tts_engine_ja = ja_engine
        draft.tts_voice_en = en_voice
        draft.tts_voice_ja = ja_voice
        try:
            updated = draft.snapshot()
            self._settings_commit(updated)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self.dialog,
                "설정 저장 실패",
                str(exc),
            )
            return
        self._draft = updated.draft()
        self.dialog.settingsChanged.emit(updated)  # type: ignore[attr-defined]
        self._wait_for_status_probe()
        self.dialog.accept()

    # ── AnkiConnect ────────────────────────────────────────────────
    def _test_ankiconnect(self) -> None:
        url = self.ui.ankiconnect_url.text().strip() or "http://127.0.0.1:8765"
        worker = _AnkiConnectTestWorker(url)
        if not self._run_network_test(worker, self._on_ankiconnect_test_finished):
            return
        self.ui.ankiconnect_test_btn.setEnabled(False)
        set_status_state(self.ui.ankiconnect_status, "pending")
        self.ui.ankiconnect_status.setText("연결 테스트 중…")

    @QtCore.Slot(bool, str)
    def _on_ankiconnect_test_finished(self, ok: bool, message: str) -> None:
        self.ui.ankiconnect_test_btn.setEnabled(True)
        if ok:
            set_status_state(self.ui.ankiconnect_status, "ok")
            self.ui.ankiconnect_status.setText("✓ 연결됨")
        else:
            set_status_state(self.ui.ankiconnect_status, "error")
            self.ui.ankiconnect_status.setText(message or "응답 없음")

    # ── Google Vision API key ──────────────────────────────────────
    def _refresh_gv_key_status(self) -> None:
        self._apply_gv_key_status(secret_store.is_set("google_vision_api_key"))

    def _apply_gv_key_status(self, is_set: bool) -> None:
        if is_set:
            set_status_state(self.ui.gv_key_status, "ok")
            self.ui.gv_key_status.setText("✓ Keychain에 저장됨")
        else:
            set_status_state(self.ui.gv_key_status, "muted")
            self.ui.gv_key_status.setText("저장된 키가 없습니다")

    def _save_gv_key(self) -> None:
        value = self.ui.gv_key_edit.text().strip()
        if not value:
            set_status_state(self.ui.gv_key_status, "error")
            self.ui.gv_key_status.setText("키를 입력하세요")
            return
        try:
            secret_store.set("google_vision_api_key", value)
        except Exception as exc:
            set_status_state(self.ui.gv_key_status, "error")
            self.ui.gv_key_status.setText(f"저장 실패: {type(exc).__name__}")
            return
        self.ui.gv_key_edit.clear()
        self._refresh_gv_key_status()

    def _clear_gv_key(self) -> None:
        secret_store.delete("google_vision_api_key")
        self.ui.gv_key_edit.clear()
        self._refresh_gv_key_status()

    def _test_gv_key(self) -> None:
        key = secret_store.get("google_vision_api_key")
        if not key:
            set_status_state(self.ui.gv_key_status, "error")
            self.ui.gv_key_status.setText("키 미설정")
            return
        worker = _GoogleVisionKeyTestWorker(
            key,
            self._draft.google_vision_endpoint,
        )
        if not self._run_network_test(worker, self._on_gv_key_test_finished):
            return
        self.ui.gv_key_test_btn.setEnabled(False)
        set_status_state(self.ui.gv_key_status, "muted")
        self.ui.gv_key_status.setText("키 테스트 중…")

    @QtCore.Slot(bool, str)
    def _on_gv_key_test_finished(self, ok: bool, message: str) -> None:
        self.ui.gv_key_test_btn.setEnabled(True)
        if not ok:
            set_status_state(self.ui.gv_key_status, "error")
            self.ui.gv_key_status.setText(message or "키 테스트 실패")
            return
        set_status_state(self.ui.gv_key_status, "ok")
        self.ui.gv_key_status.setText("✓ 키가 정상입니다")

    def _run_network_test(self, worker: QtCore.QObject, finished_slot) -> bool:
        if self._is_network_test_running():
            self._set_busy_test_message()
            return False

        self._network_test_worker = worker
        self._network_test_task.start(
            worker,
            run=worker.run,  # type: ignore[attr-defined]
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,  # type: ignore[attr-defined]
                    lambda ok, *_values: TaskTerminal.SUCCESS if ok else TaskTerminal.FAILURE,
                    finished_slot,
                )
            ],
        )
        return True

    def _is_network_test_running(self) -> bool:
        return self._network_test_task.is_running()

    @QtCore.Slot()
    def _clear_network_test(self) -> None:
        self._network_test_thread = None
        self._network_test_worker = None

    @QtCore.Slot(object)
    def _on_network_task_terminal(self, _outcome: object) -> None:
        self._clear_network_test()

    def _set_busy_test_message(self) -> None:
        set_status_state(self.ui.ankiconnect_status, "error")
        set_status_state(self.ui.gv_key_status, "error")
        self.ui.ankiconnect_status.setText("진행 중인 테스트가 끝난 뒤 다시 시도하세요.")
        self.ui.gv_key_status.setText("진행 중인 테스트가 끝난 뒤 다시 시도하세요.")

    def _is_install_running(self) -> bool:
        if self._install_thread is None:
            return False
        try:
            return self._install_thread.isRunning()
        except RuntimeError:
            self._install_thread = None
            return False

    def _is_sample_running(self) -> bool:
        if self._sample_thread is not None:
            try:
                return self._sample_thread.isRunning()
            except RuntimeError:
                self._sample_thread = None
        return self._sample_task.is_running()

    def _set_busy_tts_message(self, *, sample: bool = False) -> None:
        self.ui.tabs.setCurrentIndex(2)
        if sample:
            self.ui.tts_license_label.setText("샘플 생성이 끝난 뒤 다시 시도하세요.")
            return
        self.ui.tts_install_status.setText("설치/삭제 작업이 끝난 뒤 다시 시도하세요.")

    def _ready_for_close_or_save(self) -> bool:
        if self._is_network_test_running():
            self._set_busy_test_message()
            return False
        if self._is_install_running():
            self._set_busy_tts_message()
            return False
        if self._is_sample_running():
            self._set_busy_tts_message(sample=True)
            return False
        return True

    def _is_status_probe_running(self) -> bool:
        return self._status_task.is_running()

    def _wait_for_status_probe(self) -> None:
        if self._status_probe_timer.isActive():
            self._status_probe_timer.stop()
        self._status_task.close()
        self._clear_status_probe()

    # ── TTS install / sample / cache ───────────────────────────────
    def _install_engine(self, name: str) -> None:
        """Run the install worker for ``name`` (kokoro|voicevox|edge)."""
        if self._install_thread is not None:
            return
        from app.ui.tts_install_worker import (
            EdgeTtsInstallWorker,
            KokoroInstallWorker,
            VoicevoxInstallWorker,
        )

        worker_cls = {
            "kokoro": KokoroInstallWorker,
            "voicevox": VoicevoxInstallWorker,
            "edge": EdgeTtsInstallWorker,
        }.get(name)
        if worker_cls is None:
            return

        for btn in (
            self.ui.tts_install_btn,
            self.ui.voicevox_install_btn,
            self.ui.edge_install_btn,
        ):
            btn.setEnabled(False)
        self.ui.tts_install_status.setText(f"{name} 설치 시작 — 수십 초~수 분 걸릴 수 있습니다.")

        self._install_thread = QtCore.QThread(self.dialog)
        worker = worker_cls()
        worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(worker.run)
        worker.progress.connect(self.ui.tts_install_status.setText)
        worker.open_url.connect(lambda url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)))
        worker.finished.connect(lambda ok, msg: self._on_install_finished(ok, msg, worker))
        self._install_thread.start()

    def _on_install_finished(self, ok: bool, msg: str, worker) -> None:
        self.ui.tts_install_status.setText(msg)
        if self._install_thread is not None:
            self._install_thread.quit()
            self._install_thread.wait()
            self._install_thread = None
        worker.deleteLater()
        # Installs/uninstalls invalidate the managed worker's warm pipelines.
        from app.tts.broker import close_tts_broker

        close_tts_broker()
        # Re-import to pick up freshly installed packages.
        try:
            import sys

            for name in list(sys.modules):
                if name.startswith("kokoro") or name == "soundfile":
                    del sys.modules[name]
        except Exception:
            pass
        current_en = self.ui.tts_engine_en_combo.currentData()
        current_ja = self.ui.tts_engine_ja_combo.currentData()
        self._populate_engine_combo(self.ui.tts_engine_en_combo, "en")
        self._populate_engine_combo(self.ui.tts_engine_ja_combo, "ja")
        for combo, val in (
            (self.ui.tts_engine_en_combo, current_en),
            (self.ui.tts_engine_ja_combo, current_ja),
        ):
            idx = combo.findData(val)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self._refresh_voices("en")
        self._refresh_voices("ja")
        self._refresh_install_status()

    def _uninstall_engine(self, name: str) -> None:
        """Run an uninstall worker after a confirmation dialog."""
        if self._install_thread is not None:
            return
        from app.ui.tts_install_worker import (
            EdgeTtsUninstallWorker,
            KokoroUninstallWorker,
            VoicevoxUninstallWorker,
            kokoro_model_cache_size,
        )

        worker_cls = {
            "kokoro": KokoroUninstallWorker,
            "voicevox": VoicevoxUninstallWorker,
            "edge": EdgeTtsUninstallWorker,
        }.get(name)
        if worker_cls is None:
            return

        if name == "kokoro":
            cache_mb = kokoro_model_cache_size() / 1024 / 1024
            detail = (
                f"Kokoro 패키지 (kokoro, soundfile)와 모델 캐시 "
                f"(~{cache_mb:.0f}MB)를 삭제합니다.\n\n"
                "torch / numpy 같은 공유 의존성은 다른 프로그램에서 쓰일 수 "
                "있어 함께 삭제하지 않습니다."
            )
        elif name == "voicevox":
            detail = "Homebrew로 설치한 VOICEVOX 앱을 삭제합니다."
        else:
            detail = "pipx로 설치된 edge-tts를 삭제합니다."

        reply = QtWidgets.QMessageBox.question(
            self.dialog,
            "삭제 확인",
            detail,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        for btn in (
            self.ui.tts_install_btn,
            self.ui.voicevox_install_btn,
            self.ui.edge_install_btn,
            self.ui.kokoro_uninstall_btn,
            self.ui.voicevox_uninstall_btn,
            self.ui.edge_uninstall_btn,
        ):
            btn.setEnabled(False)
        self.ui.tts_install_status.setText(f"{name} 삭제 중…")

        self._install_thread = QtCore.QThread(self.dialog)
        worker = worker_cls()
        worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(worker.run)
        worker.progress.connect(self.ui.tts_install_status.setText)
        worker.finished.connect(lambda ok, msg: self._on_install_finished(ok, msg, worker))
        self._install_thread.start()

    def _install_or_open_voicevox(self) -> None:
        from app.ui.tts_install_worker import brew_available

        if brew_available():
            self._install_engine("voicevox")
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(VOICEVOX_DOWNLOAD_URL))
            self.ui.tts_install_status.setText(
                "Homebrew가 없어 VOICEVOX 다운로드 페이지를 열었습니다."
            )

    def _install_or_copy_edge(self) -> None:
        from app.ui.tts_install_worker import brew_available, pipx_available

        if pipx_available() or brew_available():
            self._install_engine("edge")
        else:
            QtWidgets.QApplication.clipboard().setText(EDGE_TTS_INSTALL_HINT)
            self.ui.tts_install_status.setText(
                f"pipx/brew가 없어 명령을 복사했습니다: {EDGE_TTS_INSTALL_HINT}"
            )

    def _play_sample(self, language: str) -> None:
        from app.tts.audio_cache import (
            cached_path,
            wordbook_audio_dir,
        )

        if language == "en":
            engine = self.ui.tts_engine_en_combo.currentData()
            voice = self.ui.tts_voice_en_combo.currentData()
            text = SAMPLE_TEXT_EN
            btn = self.ui.tts_sample_en_btn
        else:
            engine = self.ui.tts_engine_ja_combo.currentData()
            voice = self.ui.tts_voice_ja_combo.currentData()
            text = SAMPLE_TEXT_JA
            btn = self.ui.tts_sample_ja_btn

        if not engine or engine == "none" or not voice:
            self.ui.tts_license_label.setText("샘플 재생 전 엔진/음성을 선택하세요.")
            return

        sample_draft = deepcopy(self._draft)
        sample_draft.tts_engine_en = self.ui.tts_engine_en_combo.currentData() or "none"
        sample_draft.tts_engine_ja = self.ui.tts_engine_ja_combo.currentData() or "none"
        sample_draft.tts_voice_en = self.ui.tts_voice_en_combo.currentData() or ""
        sample_draft.tts_voice_ja = self.ui.tts_voice_ja_combo.currentData() or ""
        settings = sample_draft.snapshot()

        out_path = cached_path(
            language,
            engine,
            voice,
            text,
            bitrate=getattr(settings, "tts_bitrate", ""),
            sample_rate=getattr(settings, "tts_sample_rate", None),
            cache_dir=wordbook_audio_dir(settings, language),
        )
        if out_path is not None:
            self._play_audio_file(out_path)
            return

        # First time for this (engine, voice) — synthesis happens on a
        # background thread because Kokoro warms torch and loads a large
        # local model, which would freeze the UI.
        if self._is_sample_running():
            return
        btn.setEnabled(False)
        btn.setText("…")

        # Be honest about what's about to happen. Runtime synthesis must
        # never download; the model cache is prepared by the installer.
        if engine == "kokoro":
            from app.ui.tts_install_worker import kokoro_model_cache_size

            if kokoro_model_cache_size() < 100 * 1024 * 1024:  # < 100MB → not cached yet
                self.ui.tts_license_label.setText(
                    "Kokoro 로컬 모델 캐시가 없습니다. 설정의 Kokoro 설치를 먼저 실행하세요."
                )
            else:
                self.ui.tts_license_label.setText("샘플 생성 중…")
        else:
            self.ui.tts_license_label.setText("샘플 생성 중…")

        worker = _SampleSynthWorker(settings, language, text)
        self._sample_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    lambda ok, *_values: TaskTerminal.SUCCESS if ok else TaskTerminal.FAILURE,
                    lambda ok, msg, path: self._on_sample_finished(
                        ok,
                        msg,
                        path,
                        btn,
                    ),
                )
            ],
        )

    def _on_sample_finished(self, ok, msg, path, btn) -> None:
        btn.setEnabled(True)
        btn.setText("▶")
        if ok and path is not None:
            self.ui.tts_license_label.setText("")
            self._play_audio_file(path)
            self._refresh_license_label()
        else:
            self.ui.tts_license_label.setText(msg or "샘플 생성 실패")

    def _play_audio_file(self, path: Path) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        player = QMediaPlayer(self.dialog)
        audio_out = QAudioOutput(self.dialog)
        player.setAudioOutput(audio_out)
        player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        player.play()
        self._sample_player = (player, audio_out)

    def _clear_tts_cache(self) -> None:
        from app.tts.audio_cache import clear_cache, wordbook_audio_dir

        settings = self._draft.snapshot()
        n = clear_cache(
            [
                wordbook_audio_dir(settings, "en"),
                wordbook_audio_dir(settings, "ja"),
            ]
        )
        self.ui.tts_cache_status.setText(f"{n}개 파일 삭제됨")


class SettingsFormBinder:
    """Owns snapshot-to-form loading and validated form commit."""

    def __init__(self, runtime: _SettingsRuntime) -> None:
        self._runtime = runtime

    def load(self, settings: AppSettings | SettingsDraft) -> None:
        self._runtime._load(settings)

    def save(self) -> None:
        self._runtime._save()


class SettingsTaskCoordinator:
    """Owns status probes, network tests, key actions, and close gating."""

    def __init__(self, runtime: _SettingsRuntime) -> None:
        self._runtime = runtime

    def start_status_probe(self) -> None:
        self._runtime._start_status_probe()

    def ready_for_close_or_save(self) -> bool:
        return self._runtime._ready_for_close_or_save()

    def close(self) -> None:
        self._runtime._wait_for_status_probe()


class TtsManagementController:
    """Owns TTS engine/voice/install/sample/cache behavior."""

    def __init__(self, runtime: _SettingsRuntime) -> None:
        self._runtime = runtime

    def refresh_voices(self, language: str) -> None:
        self._runtime._refresh_voices(language)

    def install(self, name: str) -> None:
        self._runtime._install_engine(name)

    def uninstall(self, name: str) -> None:
        self._runtime._uninstall_engine(name)

    def play_sample(self, language: str) -> None:
        self._runtime._play_sample(language)

    def clear_cache(self) -> None:
        self._runtime._clear_tts_cache()


class SettingsController:
    """Composition root retaining one-release method/state compatibility."""

    def __init__(
        self,
        dialog: QtWidgets.QDialog,
        ui: SettingsUiRefs,
        draft: SettingsDraft,
        store,
        settings_commit,
    ) -> None:
        self._runtime = _SettingsRuntime(
            dialog,
            ui,
            draft,
            store,
            settings_commit,
        )
        self.form_binder = SettingsFormBinder(self._runtime)
        self.task_coordinator = SettingsTaskCoordinator(self._runtime)
        self.tts_management = TtsManagementController(self._runtime)

    def _load(self, settings: AppSettings | SettingsDraft) -> None:
        self.form_binder.load(settings)

    def _save(self) -> None:
        self.form_binder.save()

    def _ready_for_close_or_save(self) -> bool:
        return self.task_coordinator.ready_for_close_or_save()

    def _wait_for_status_probe(self) -> None:
        self.task_coordinator.close()

    def __getattr__(self, name: str):
        runtime = self.__dict__.get("_runtime")
        if runtime is not None and hasattr(runtime, name):
            return getattr(runtime, name)
        raise AttributeError(name)

    @property
    def _draft(self) -> SettingsDraft:
        return self._runtime._draft

    @_draft.setter
    def _draft(self, value: SettingsDraft) -> None:
        self._runtime._draft = value

    @property
    def _install_thread(self):
        return self._runtime._install_thread

    @_install_thread.setter
    def _install_thread(self, value) -> None:
        self._runtime._install_thread = value

    @property
    def _sample_thread(self):
        return self._runtime._sample_thread

    @_sample_thread.setter
    def _sample_thread(self, value) -> None:
        self._runtime._sample_thread = value

    @property
    def _status_probe_timer(self):
        return self._runtime._status_probe_timer


__all__ = [
    "SettingsController",
    "SettingsFormBinder",
    "SettingsTaskCoordinator",
    "TtsManagementController",
]
