from __future__ import annotations

from PySide6 import QtGui

from app.storage.settings_store import SettingsStore
from app.ui.settings_view import SettingsDialog


class _RunningThread:
    def isRunning(self) -> bool:  # noqa: N802 - Qt-style test double
        return True


def test_settings_dialog_blocks_save_while_tts_install_is_running(qtbot, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(store, initial_settings=store.load())
    qtbot.addWidget(dialog)

    dialog._install_thread = _RunningThread()  # type: ignore[assignment]

    dialog._save()

    assert dialog.tabs.currentIndex() == 2
    assert dialog.tts_install_status.text() == "설치/삭제 작업이 끝난 뒤 다시 시도하세요."
    assert dialog.result() == 0


def test_settings_dialog_blocks_close_while_tts_sample_is_running(qtbot, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(store, initial_settings=store.load())
    qtbot.addWidget(dialog)

    dialog._sample_thread = _RunningThread()  # type: ignore[assignment]
    event = QtGui.QCloseEvent()

    dialog.closeEvent(event)

    assert not event.isAccepted()
    assert dialog.tabs.currentIndex() == 2
    assert dialog.tts_license_label.text() == "샘플 생성이 끝난 뒤 다시 시도하세요."
