from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from app.core.settings import AppSettings, SettingsDraft, settings_snapshot
from app.storage.settings_store import SettingsStore
from app.ui.dialog_shortcuts import install_standard_close_shortcut
from app.ui.settings_builders import SettingsUiBuilder
from app.ui.settings_contract import (
    EDGE_TTS_INSTALL_HINT,
    SAMPLE_TEXT_EN,
    SAMPLE_TEXT_JA,
    VOICEVOX_DOWNLOAD_URL,
)
from app.ui.settings_controller import SettingsController
from app.ui.settings_widgets import _settings_combo


class SettingsDialog(QtWidgets.QDialog):
    """Stable Qt façade composed from a builder, UI refs, and controller."""

    settingsChanged = QtCore.Signal(object)

    def __init__(
        self,
        store: SettingsStore,
        parent: QtWidgets.QWidget | None = None,
        initial_settings: AppSettings | SettingsDraft | None = None,
        settings_commit: Callable[[AppSettings], object] | None = None,
    ) -> None:
        super().__init__(parent)
        initial_snapshot = (
            settings_snapshot(initial_settings) if initial_settings is not None else store.load()
        )
        self.setObjectName("settingsDialog")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setWindowTitle("설정")
        self.resize(900, 720)
        self.setMinimumWidth(820)
        install_standard_close_shortcut(self)

        self._ui = SettingsUiBuilder(self, self).build()
        self._ui.expose_legacy_facade(self)
        self._controller = SettingsController(
            self,
            self._ui,
            initial_snapshot.draft(),
            store,
            settings_commit or store.save,
        )
        self._form_binder = self._controller.form_binder
        self._task_coordinator = self._controller.task_coordinator
        self._tts_management = self._controller.tts_management
        self._form_binder.load(initial_snapshot)
        self._controller._status_probe_timer.start(0)

    def _call_controller(self, name: str, *args, **kwargs):
        return getattr(self._controller, name)(*args, **kwargs)

    # Signal targets and externally characterized methods stay on the dialog.
    def _save(self) -> None:
        self._call_controller("_save")

    def _save_gv_key(self) -> None:
        self._call_controller("_save_gv_key")

    def _clear_gv_key(self) -> None:
        self._call_controller("_clear_gv_key")

    def _test_gv_key(self) -> None:
        self._call_controller("_test_gv_key")

    def _test_ankiconnect(self) -> None:
        self._call_controller("_test_ankiconnect")

    def _install_engine(self, name: str) -> None:
        self._call_controller("_install_engine", name)

    def _uninstall_engine(self, name: str) -> None:
        self._call_controller("_uninstall_engine", name)

    def _install_or_open_voicevox(self) -> None:
        self._call_controller("_install_or_open_voicevox")

    def _install_or_copy_edge(self) -> None:
        self._call_controller("_install_or_copy_edge")

    def _refresh_voices(self, language: str) -> None:
        self._call_controller("_refresh_voices", language)

    def _refresh_voice_add_visibility(self) -> None:
        self._call_controller("_refresh_voice_add_visibility")

    def _open_voicevox_picker(self) -> None:
        self._call_controller("_open_voicevox_picker")

    def _play_sample(self, language: str) -> None:
        self._call_controller("_play_sample", language)

    def _clear_tts_cache(self) -> None:
        self._call_controller("_clear_tts_cache")

    def reject(self) -> None:
        if not self._controller._ready_for_close_or_save():
            return
        self._controller._wait_for_status_probe()
        super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self._controller._ready_for_close_or_save():
            event.ignore()
            return
        self._controller._wait_for_status_probe()
        super().closeEvent(event)

    def __getattr__(self, name: str):
        """One-release compatibility façade for characterized private methods."""
        controller = self.__dict__.get("_controller")
        if controller is not None and name.startswith("_") and hasattr(controller, name):
            return getattr(controller, name)
        raise AttributeError(name)

    @property
    def _draft(self) -> SettingsDraft:
        return self._controller._draft

    @_draft.setter
    def _draft(self, value: SettingsDraft) -> None:
        self._controller._draft = value

    @property
    def _install_thread(self):
        return self._controller._install_thread

    @_install_thread.setter
    def _install_thread(self, value) -> None:
        self._controller._install_thread = value

    @property
    def _sample_thread(self):
        return self._controller._sample_thread

    @_sample_thread.setter
    def _sample_thread(self, value) -> None:
        self._controller._sample_thread = value

    @property
    def _status_probe_timer(self):
        return self._controller._status_probe_timer


__all__ = [
    "EDGE_TTS_INSTALL_HINT",
    "SAMPLE_TEXT_EN",
    "SAMPLE_TEXT_JA",
    "SettingsDialog",
    "VOICEVOX_DOWNLOAD_URL",
    "_settings_combo",
]
