from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.storage import secret_store
from app.storage.settings_store import Settings
from app.ui.settings_widgets import _VoicevoxVoicePicker, set_status_state
from app.ui.settings_workers import (
    _AnkiConnectTestWorker,
    _GoogleVisionKeyTestWorker,
    _SampleSynthWorker,
    _SettingsStatusWorker,
)

SAMPLE_TEXT_EN = "apple"
SAMPLE_TEXT_JA = "りんご"
VOICEVOX_DOWNLOAD_URL = "https://voicevox.hiroshiba.jp/"
EDGE_TTS_INSTALL_HINT = "pipx install edge-tts"


class SettingsRuntimeMixin:
    # ── engine combos ──────────────────────────────────────────────
    def _populate_engine_combo(self, combo: QtWidgets.QComboBox, language: str) -> None:
        from app.anki.tts import list_provider_classes

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("사용 안 함", "none")
        for name, cls in list_provider_classes().items():
            info = cls.info()
            voices = info.voices_ja if language == "ja" else info.voices_en
            if not voices:
                continue
            label = info.display_name
            if not info.available:
                label = f"{label} (미설치)"
            combo.addItem(label, name)
        combo.blockSignals(False)

    def _refresh_voices(self, language: str) -> None:
        if language == "en":
            engine_combo = self.tts_engine_en_combo
            voice_combo = self.tts_voice_en_combo
        else:
            engine_combo = self.tts_engine_ja_combo
            voice_combo = self.tts_voice_ja_combo
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
        is_voicevox = self.tts_engine_ja_combo.currentData() == "voicevox"
        self.tts_voice_add_btn.setVisible(is_voicevox)

    def _open_voicevox_picker(self) -> None:
        from app.anki.tts.voicevox_provider import VoicevoxProvider

        if not VoicevoxProvider.is_running():
            self.tts_license_label.setText(
                "VOICEVOX 엔진이 가동 중이 아닙니다. 앱을 실행한 뒤 다시 시도하세요."
            )
            return

        settings = self._store.load()
        all_voices = VoicevoxProvider.fetch_voices(settings.voicevox_url)
        if not all_voices:
            self.tts_license_label.setText("VOICEVOX 음성 목록을 불러오지 못했습니다.")
            return

        current = set(settings.tts_voicevox_voices)
        dlg = _VoicevoxVoicePicker(all_voices, current, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        chosen = dlg.selected()
        if not chosen:
            return
        # Persist and refresh the JA voice combo so the new selection is
        # visible immediately.
        self._store.update(tts_voicevox_voices=chosen)
        self._refresh_voices("ja")

    def _voices_for(self, engine: str, language: str) -> tuple[str, ...]:
        """Per-engine voice list — for VOICEVOX, return the user's saved
        curated list (defaults to the 5 standard voices). The "+" button
        lets the user pull from the live engine catalog."""
        from app.anki.tts import get_provider_info

        if engine == "voicevox" and language == "ja":
            settings = self._store.load()
            return tuple(settings.tts_voicevox_voices) or ()
        info = get_provider_info(engine)
        return info.voices_ja if language == "ja" else info.voices_en

    def _refresh_license_label(self) -> None:
        from app.anki.tts import get_provider_info

        notes: list[str] = []
        for combo, lang in (
            (self.tts_engine_en_combo, "EN"),
            (self.tts_engine_ja_combo, "JA"),
        ):
            name = combo.currentData()
            if not name or name == "none":
                continue
            info = get_provider_info(name)
            line = f"{lang} {info.display_name} — {info.license_note}"
            if info.usage_warning:
                line += f"  ⚠ {info.usage_warning}"
            notes.append(line)
        self.tts_license_label.setText("\n".join(notes))

    def _make_uninstall_btn(self, engine_name: str, tooltip: str, handler) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton("")
        btn.setObjectName("settingsSecondaryButton")
        btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
        btn.setIconSize(QtCore.QSize(15, 15))
        btn.setMaximumWidth(40)
        btn.setToolTip(f"{engine_name} 삭제 — {tooltip}")
        btn.clicked.connect(handler)
        btn.hide()
        return btn

    def _refresh_install_status(self) -> None:
        from app.anki.tts import get_provider_info
        from app.ui.tts_install_worker import (
            brew_available, kokoro_model_cache_size,
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
            self.tts_install_btn.setEnabled(False)
            self.tts_install_btn.setText("Kokoro ✓")
            self.kokoro_uninstall_btn.show()
            if kokoro_cache_mb > 1:
                self.kokoro_uninstall_btn.setToolTip(
                    f"Kokoro 삭제 — 패키지 + 모델 캐시(~{kokoro_cache_mb:.0f}MB) 정리"
                )
        else:
            self.tts_install_btn.setEnabled(True)
            self.tts_install_btn.setText("Kokoro 설치")
            self.kokoro_uninstall_btn.hide()

        # VOICEVOX never runs through brew (no cask exists) — always
        # surfaces the download page, so be upfront about it.
        self.voicevox_install_btn.setText("VOICEVOX 다운로드")
        # We can't reliably tell whether VOICEVOX is installed (it could
        # be a brew cask, a manual /Applications drop, or absent), so the
        # uninstall button is always available when brew is around — its
        # worker reports gracefully if there's nothing to uninstall.
        self.voicevox_uninstall_btn.setVisible(brew_is_available)

        if edge_available:
            self.edge_install_btn.setEnabled(False)
            self.edge_install_btn.setText("edge-tts ✓")
            self.edge_uninstall_btn.show()
        else:
            self.edge_install_btn.setEnabled(True)
            self.edge_install_btn.setText("edge-tts 설치")
            self.edge_uninstall_btn.hide()
        self.tts_install_status.setText("")

    # ── load / save ────────────────────────────────────────────────
    def _load(self, settings: Settings) -> None:
        self.excel_dir.set_path(settings.default_excel_dir)
        self.excel_en.set_path(settings.excel_path_en or settings.excel_path_for("en"))
        self.excel_ja.set_path(settings.excel_path_ja or settings.excel_path_for("ja"))
        self.anki_dir.set_path(settings.default_anki_export_dir)
        self.anki_en.set_path(settings.anki_path_en or settings.anki_path_for("en"))
        self.anki_ja.set_path(settings.anki_path_ja or settings.anki_path_for("ja"))
        self.delay.setValue(settings.request_delay_seconds)
        self.cache_check.setChecked(settings.cache_enabled)
        self.preview_check.setChecked(settings.show_preview)
        idx = self.dup_combo.findData(settings.duplicate_policy)
        if idx >= 0:
            self.dup_combo.setCurrentIndex(idx)
        self.deck_name.setText(settings.default_deck_name)
        idx = self.provider_combo.findData(settings.provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.ankiconnect_check.setChecked(settings.ankiconnect_enabled)
        self.ankiconnect_url.setText(settings.ankiconnect_url)

        idx = self.ocr_combo.findData(getattr(settings, "ocr_provider", "apple_vision"))
        if idx >= 0:
            self.ocr_combo.setCurrentIndex(idx)
        set_status_state(self.gv_key_status, "muted")
        self.gv_key_status.setText("키 상태 확인 중…")

        self.tts_enabled_check.setChecked(settings.tts_enabled)
        self.tts_play_front_check.setChecked(settings.tts_play_front)
        self.tts_play_back_check.setChecked(settings.tts_play_back)
        self.tts_play_examples_check.setChecked(settings.tts_play_examples)
        self.tts_pre_generate_check.setChecked(settings.tts_pre_generate_on_save)

        self._populate_engine_combo(self.tts_engine_en_combo, "en")
        self._populate_engine_combo(self.tts_engine_ja_combo, "ja")
        idx = self.tts_engine_en_combo.findData(settings.tts_engine_en)
        if idx >= 0:
            self.tts_engine_en_combo.setCurrentIndex(idx)
        idx = self.tts_engine_ja_combo.findData(settings.tts_engine_ja)
        if idx >= 0:
            self.tts_engine_ja_combo.setCurrentIndex(idx)
        self._refresh_voices("en")
        self._refresh_voices("ja")
        idx = self.tts_voice_en_combo.findData(settings.tts_voice_en)
        if idx >= 0:
            self.tts_voice_en_combo.setCurrentIndex(idx)
        idx = self.tts_voice_ja_combo.findData(settings.tts_voice_ja)
        if idx >= 0:
            self.tts_voice_ja_combo.setCurrentIndex(idx)
        self.tts_install_status.setText("설치 상태 확인 중…")
        self._refresh_voice_add_visibility()

    def _start_status_probe(self) -> None:
        if self._status_thread is not None:
            return
        thread = QtCore.QThread(self)
        worker = _SettingsStatusWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_status_probe_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_status_probe)
        self._status_thread = thread
        self._status_worker = worker
        thread.start()

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

    def _save(self) -> None:
        if not self._ready_for_close_or_save():
            return
        en_engine = self.tts_engine_en_combo.currentData() or "none"
        ja_engine = self.tts_engine_ja_combo.currentData() or "none"
        en_voice = self.tts_voice_en_combo.currentData() or ""
        ja_voice = self.tts_voice_ja_combo.currentData() or ""
        updated = self._store.update(
            default_excel_dir=self.excel_dir.path() or "",
            excel_path_en=self.excel_en.path() or "",
            excel_path_ja=self.excel_ja.path() or "",
            default_anki_export_dir=self.anki_dir.path() or "",
            anki_path_en=self.anki_en.path() or "",
            anki_path_ja=self.anki_ja.path() or "",
            request_delay_seconds=float(self.delay.value()),
            cache_enabled=self.cache_check.isChecked(),
            show_preview=self.preview_check.isChecked(),
            duplicate_policy=self.dup_combo.currentData(),
            default_deck_name=self.deck_name.text().strip() or "JellyDict",
            provider=self.provider_combo.currentData(),
            ankiconnect_enabled=self.ankiconnect_check.isChecked(),
            ankiconnect_url=self.ankiconnect_url.text().strip() or "http://127.0.0.1:8765",
            ocr_provider=self.ocr_combo.currentData() or "apple_vision",
            tts_enabled=self.tts_enabled_check.isChecked(),
            tts_play_front=self.tts_play_front_check.isChecked(),
            tts_play_back=self.tts_play_back_check.isChecked(),
            tts_play_examples=self.tts_play_examples_check.isChecked(),
            tts_pre_generate_on_save=self.tts_pre_generate_check.isChecked(),
            tts_engine_en=en_engine,
            tts_engine_ja=ja_engine,
            tts_voice_en=en_voice,
            tts_voice_ja=ja_voice,
        )
        self.settingsChanged.emit(updated)
        self._wait_for_status_probe()
        self.accept()

    # ── AnkiConnect ────────────────────────────────────────────────
    def _test_ankiconnect(self) -> None:
        url = self.ankiconnect_url.text().strip() or "http://127.0.0.1:8765"
        worker = _AnkiConnectTestWorker(url)
        if not self._run_network_test(worker, self._on_ankiconnect_test_finished):
            return
        self.ankiconnect_test_btn.setEnabled(False)
        set_status_state(self.ankiconnect_status, "pending")
        self.ankiconnect_status.setText("연결 테스트 중…")

    @QtCore.Slot(bool, str)
    def _on_ankiconnect_test_finished(self, ok: bool, message: str) -> None:
        self.ankiconnect_test_btn.setEnabled(True)
        if ok:
            set_status_state(self.ankiconnect_status, "ok")
            self.ankiconnect_status.setText("✓ 연결됨")
        else:
            set_status_state(self.ankiconnect_status, "error")
            self.ankiconnect_status.setText(message or "응답 없음")

    # ── Google Vision API key ──────────────────────────────────────
    def _refresh_gv_key_status(self) -> None:
        self._apply_gv_key_status(secret_store.is_set("google_vision_api_key"))

    def _apply_gv_key_status(self, is_set: bool) -> None:
        if is_set:
            set_status_state(self.gv_key_status, "ok")
            self.gv_key_status.setText("✓ Keychain에 저장됨")
        else:
            set_status_state(self.gv_key_status, "muted")
            self.gv_key_status.setText("저장된 키가 없습니다")

    def _save_gv_key(self) -> None:
        value = self.gv_key_edit.text().strip()
        if not value:
            set_status_state(self.gv_key_status, "error")
            self.gv_key_status.setText("키를 입력하세요")
            return
        try:
            secret_store.set("google_vision_api_key", value)
        except Exception as exc:
            set_status_state(self.gv_key_status, "error")
            self.gv_key_status.setText(f"저장 실패: {type(exc).__name__}")
            return
        self.gv_key_edit.clear()
        self._refresh_gv_key_status()

    def _clear_gv_key(self) -> None:
        secret_store.delete("google_vision_api_key")
        self.gv_key_edit.clear()
        self._refresh_gv_key_status()

    def _test_gv_key(self) -> None:
        key = secret_store.get("google_vision_api_key")
        if not key:
            set_status_state(self.gv_key_status, "error")
            self.gv_key_status.setText("키 미설정")
            return
        settings = self._store.load()
        worker = _GoogleVisionKeyTestWorker(key, settings.google_vision_endpoint)
        if not self._run_network_test(worker, self._on_gv_key_test_finished):
            return
        self.gv_key_test_btn.setEnabled(False)
        set_status_state(self.gv_key_status, "muted")
        self.gv_key_status.setText("키 테스트 중…")

    @QtCore.Slot(bool, str)
    def _on_gv_key_test_finished(self, ok: bool, message: str) -> None:
        self.gv_key_test_btn.setEnabled(True)
        if not ok:
            set_status_state(self.gv_key_status, "error")
            self.gv_key_status.setText(message or "키 테스트 실패")
            return
        set_status_state(self.gv_key_status, "ok")
        self.gv_key_status.setText("✓ 키가 정상입니다")

    def _run_network_test(self, worker: QtCore.QObject, finished_slot) -> bool:
        if self._is_network_test_running():
            self._set_busy_test_message()
            return False

        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)  # type: ignore[attr-defined]
        worker.finished.connect(finished_slot)  # type: ignore[attr-defined]
        worker.finished.connect(thread.quit)  # type: ignore[attr-defined]
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_network_test)
        self._network_test_thread = thread
        self._network_test_worker = worker
        thread.start()
        return True

    def _is_network_test_running(self) -> bool:
        if self._network_test_thread is None:
            return False
        try:
            return self._network_test_thread.isRunning()
        except RuntimeError:
            self._clear_network_test()
            return False

    @QtCore.Slot()
    def _clear_network_test(self) -> None:
        self._network_test_thread = None
        self._network_test_worker = None

    def _set_busy_test_message(self) -> None:
        set_status_state(self.ankiconnect_status, "error")
        set_status_state(self.gv_key_status, "error")
        self.ankiconnect_status.setText("진행 중인 테스트가 끝난 뒤 다시 시도하세요.")
        self.gv_key_status.setText("진행 중인 테스트가 끝난 뒤 다시 시도하세요.")

    def _is_install_running(self) -> bool:
        if self._install_thread is None:
            return False
        try:
            return self._install_thread.isRunning()
        except RuntimeError:
            self._install_thread = None
            return False

    def _is_sample_running(self) -> bool:
        if self._sample_thread is None:
            return False
        try:
            return self._sample_thread.isRunning()
        except RuntimeError:
            self._sample_thread = None
            return False

    def _set_busy_tts_message(self, *, sample: bool = False) -> None:
        self.tabs.setCurrentIndex(2)
        if sample:
            self.tts_license_label.setText("샘플 생성이 끝난 뒤 다시 시도하세요.")
            return
        self.tts_install_status.setText("설치/삭제 작업이 끝난 뒤 다시 시도하세요.")

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
        if self._status_thread is None:
            return False
        try:
            return self._status_thread.isRunning()
        except RuntimeError:
            self._clear_status_probe()
            return False

    def _wait_for_status_probe(self) -> None:
        if self._status_probe_timer.isActive():
            self._status_probe_timer.stop()
        if self._status_thread is None:
            return
        try:
            if self._status_thread.isRunning():
                self._status_thread.quit()
                self._status_thread.wait(1200)
        except RuntimeError:
            pass
        self._clear_status_probe()

    def reject(self) -> None:
        if not self._ready_for_close_or_save():
            return
        self._wait_for_status_probe()
        super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self._ready_for_close_or_save():
            event.ignore()
            return
        self._wait_for_status_probe()
        super().closeEvent(event)

    # ── TTS install / sample / cache ───────────────────────────────
    def _install_engine(self, name: str) -> None:
        """Run the install worker for ``name`` (kokoro|voicevox|edge)."""
        if self._install_thread is not None:
            return
        from app.ui.tts_install_worker import (
            KokoroInstallWorker, VoicevoxInstallWorker, EdgeTtsInstallWorker,
        )

        worker_cls = {
            "kokoro": KokoroInstallWorker,
            "voicevox": VoicevoxInstallWorker,
            "edge": EdgeTtsInstallWorker,
        }.get(name)
        if worker_cls is None:
            return

        for btn in (
            self.tts_install_btn, self.voicevox_install_btn, self.edge_install_btn,
        ):
            btn.setEnabled(False)
        self.tts_install_status.setText(f"{name} 설치 시작 — 수십 초~수 분 걸릴 수 있습니다.")

        self._install_thread = QtCore.QThread(self)
        worker = worker_cls()
        worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(worker.run)
        worker.progress.connect(self.tts_install_status.setText)
        worker.open_url.connect(
            lambda url: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        )
        worker.finished.connect(lambda ok, msg: self._on_install_finished(ok, msg, worker))
        self._install_thread.start()

    def _on_install_finished(self, ok: bool, msg: str, worker) -> None:
        self.tts_install_status.setText(msg)
        if self._install_thread is not None:
            self._install_thread.quit()
            self._install_thread.wait()
            self._install_thread = None
        worker.deleteLater()
        # Drop any cached providers — installs/uninstalls invalidate them.
        self._tts_provider_cache.clear()
        # Re-import to pick up freshly installed packages.
        try:
            import sys
            for name in list(sys.modules):
                if name.startswith("kokoro") or name == "soundfile":
                    del sys.modules[name]
        except Exception:
            pass
        current_en = self.tts_engine_en_combo.currentData()
        current_ja = self.tts_engine_ja_combo.currentData()
        self._populate_engine_combo(self.tts_engine_en_combo, "en")
        self._populate_engine_combo(self.tts_engine_ja_combo, "ja")
        for combo, val in (
            (self.tts_engine_en_combo, current_en),
            (self.tts_engine_ja_combo, current_ja),
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
            KokoroUninstallWorker, VoicevoxUninstallWorker, EdgeTtsUninstallWorker,
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
            self,
            "삭제 확인",
            detail,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        for btn in (
            self.tts_install_btn, self.voicevox_install_btn, self.edge_install_btn,
            self.kokoro_uninstall_btn, self.voicevox_uninstall_btn,
            self.edge_uninstall_btn,
        ):
            btn.setEnabled(False)
        self.tts_install_status.setText(f"{name} 삭제 중…")

        self._install_thread = QtCore.QThread(self)
        worker = worker_cls()
        worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(worker.run)
        worker.progress.connect(self.tts_install_status.setText)
        worker.finished.connect(lambda ok, msg: self._on_install_finished(ok, msg, worker))
        self._install_thread.start()

    def _install_or_open_voicevox(self) -> None:
        from app.ui.tts_install_worker import brew_available

        if brew_available():
            self._install_engine("voicevox")
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(VOICEVOX_DOWNLOAD_URL))
            self.tts_install_status.setText(
                "Homebrew가 없어 VOICEVOX 다운로드 페이지를 열었습니다."
            )

    def _install_or_copy_edge(self) -> None:
        from app.ui.tts_install_worker import brew_available, pipx_available

        if pipx_available() or brew_available():
            self._install_engine("edge")
        else:
            QtWidgets.QApplication.clipboard().setText(EDGE_TTS_INSTALL_HINT)
            self.tts_install_status.setText(
                f"pipx/brew가 없어 명령을 복사했습니다: {EDGE_TTS_INSTALL_HINT}"
            )

    def _play_sample(self, language: str) -> None:
        from app.anki.tts.cache import cache_path, wordbook_audio_dir

        if language == "en":
            engine = self.tts_engine_en_combo.currentData()
            voice = self.tts_voice_en_combo.currentData()
            text = SAMPLE_TEXT_EN
            btn = self.tts_sample_en_btn
        else:
            engine = self.tts_engine_ja_combo.currentData()
            voice = self.tts_voice_ja_combo.currentData()
            text = SAMPLE_TEXT_JA
            btn = self.tts_sample_ja_btn

        if not engine or engine == "none" or not voice:
            self.tts_license_label.setText("샘플 재생 전 엔진/음성을 선택하세요.")
            return

        settings = self._store.load()
        settings.tts_engine_en = self.tts_engine_en_combo.currentData() or "none"
        settings.tts_engine_ja = self.tts_engine_ja_combo.currentData() or "none"
        settings.tts_voice_en = self.tts_voice_en_combo.currentData() or ""
        settings.tts_voice_ja = self.tts_voice_ja_combo.currentData() or ""

        out_path = cache_path(
            language,
            engine,
            voice,
            text,
            bitrate=getattr(settings, "tts_bitrate", ""),
            sample_rate=getattr(settings, "tts_sample_rate", None),
            cache_dir=wordbook_audio_dir(settings, language),
        )
        if out_path.exists():
            self._play_audio_file(out_path)
            return

        # First time for this (engine, voice) — synthesis happens on a
        # background thread because Kokoro warms torch and loads a large
        # local model, which would freeze the UI.
        if getattr(self, "_sample_thread", None) is not None:
            return
        btn.setEnabled(False)
        btn.setText("…")

        # Be honest about what's about to happen. Runtime synthesis must
        # never download; the model cache is prepared by the installer.
        if engine == "kokoro":
            from app.ui.tts_install_worker import kokoro_model_cache_size

            if kokoro_model_cache_size() < 100 * 1024 * 1024:  # < 100MB → not cached yet
                self.tts_license_label.setText(
                    "Kokoro 로컬 모델 캐시가 없습니다. 설정의 Kokoro 설치를 먼저 실행하세요."
                )
            else:
                self.tts_license_label.setText("샘플 생성 중…")
        else:
            self.tts_license_label.setText("샘플 생성 중…")

        # Reuse the provider across clicks so KPipeline isn't rebuilt
        # (torch.load of the 327MB .pth is the dominant cost).
        provider = self._tts_provider_cache.get(engine)
        if provider is None:
            from app.anki.tts import build_provider

            provider = build_provider(engine, settings)
            self._tts_provider_cache[engine] = provider

        self._sample_thread = QtCore.QThread(self)
        worker = _SampleSynthWorker(provider, language, voice, text, out_path)
        worker.moveToThread(self._sample_thread)
        self._sample_thread.started.connect(worker.run)
        worker.finished.connect(
            lambda ok, msg, path: self._on_sample_finished(ok, msg, path, btn, worker)
        )
        self._sample_thread.start()

    def _on_sample_finished(self, ok, msg, path, btn, worker) -> None:
        btn.setEnabled(True)
        btn.setText("▶")
        if self._sample_thread is not None:
            self._sample_thread.quit()
            self._sample_thread.wait()
            self._sample_thread = None
        worker.deleteLater()
        if ok and path is not None:
            self.tts_license_label.setText("")
            self._play_audio_file(path)
            self._refresh_license_label()
        else:
            self.tts_license_label.setText(msg or "샘플 생성 실패")

    def _play_audio_file(self, path: Path) -> None:
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        player = QMediaPlayer(self)
        audio_out = QAudioOutput(self)
        player.setAudioOutput(audio_out)
        player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        player.play()
        self._sample_player = (player, audio_out)

    def _clear_tts_cache(self) -> None:
        from app.anki.tts.cache import clear_cache, wordbook_audio_dir

        settings = self._store.load()
        n = clear_cache(
            [
                wordbook_audio_dir(settings, "en"),
                wordbook_audio_dir(settings, "ja"),
            ]
        )
        self.tts_cache_status.setText(f"{n}개 파일 삭제됨")
