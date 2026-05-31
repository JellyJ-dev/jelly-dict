from __future__ import annotations

from PySide6 import QtWidgets

from app.core import config
from app.storage.settings_store import SettingsStore
from app.ui.developer_tools_dialog import DeveloperToolsDialog, build_diagnostics_text


def test_diagnostics_text_summarizes_environment_without_secrets(monkeypatch):
    monkeypatch.setenv("JELLY_DICT_GOOGLE_VISION_API_KEY", "SECRET-KEY")
    settings = SettingsStore().load()
    settings.ocr_provider = "google_vision"
    settings.tts_enabled = True
    SettingsStore().save(settings)
    config.log_path().write_text("one\ntwo\nthree\n", encoding="utf-8")

    text = build_diagnostics_text(config.log_path(), log_tail_lines=2)

    assert "Jelly Dict diagnostics" in text
    assert "ocr_provider: google_vision" in text
    assert "tts_enabled: True" in text
    assert "two\nthree" in text
    assert "SECRET-KEY" not in text
    assert "google_vision_api_key" not in text


def test_developer_tools_copy_diagnostics_button_updates_clipboard(qtbot, monkeypatch):
    class _Clipboard:
        text_value = ""

        def setText(self, text: str) -> None:  # noqa: N802 - Qt API
            self.text_value = text

        def text(self) -> str:
            return self.text_value

    clipboard = _Clipboard()
    monkeypatch.setattr(
        QtWidgets.QApplication,
        "clipboard",
        staticmethod(lambda: clipboard),
    )
    dialog = DeveloperToolsDialog()
    qtbot.addWidget(dialog)

    dialog._copy_diagnostics()

    assert "Jelly Dict diagnostics" in clipboard.text()
    assert dialog.status_label.text() == "진단 정보가 클립보드에 복사되었습니다."
