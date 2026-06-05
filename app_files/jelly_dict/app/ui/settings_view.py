from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.storage.settings_store import Settings, SettingsStore
from app.ui.dialog_shortcuts import install_standard_close_shortcut
from app.ui.settings_builders import SettingsBuildMixin
from app.ui.settings_runtime_mixin import (
    EDGE_TTS_INSTALL_HINT,
    SAMPLE_TEXT_EN,
    SAMPLE_TEXT_JA,
    VOICEVOX_DOWNLOAD_URL,
    SettingsRuntimeMixin,
)
from app.ui.settings_widgets import _settings_combo
from app.ui.settings_workers import _SettingsStatusWorker


class SettingsDialog(
    SettingsRuntimeMixin,
    SettingsBuildMixin,
    QtWidgets.QDialog,
):
    settingsChanged = QtCore.Signal(Settings)

    def __init__(
        self,
        store: SettingsStore,
        parent: QtWidgets.QWidget | None = None,
        initial_settings: Settings | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self.setObjectName("settingsDialog")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setWindowTitle("설정")
        self.resize(900, 720)
        self.setMinimumWidth(820)
        self._sample_player = None
        self._install_thread: QtCore.QThread | None = None
        self._sample_thread: QtCore.QThread | None = None
        self._network_test_thread: QtCore.QThread | None = None
        self._network_test_worker: QtCore.QObject | None = None
        self._status_thread: QtCore.QThread | None = None
        self._status_worker: _SettingsStatusWorker | None = None
        self._status_probe_timer = QtCore.QTimer(self)
        self._status_probe_timer.setSingleShot(True)
        self._status_probe_timer.timeout.connect(self._start_status_probe)
        # Keep TTS provider instances alive across clicks so the heavy
        # KPipeline (~327MB torch.load) is built only once per session.
        self._tts_provider_cache: dict[str, object] = {}
        install_standard_close_shortcut(self)
        self._build_ui()
        self._load(initial_settings or store.load())
        self._status_probe_timer.start(0)
