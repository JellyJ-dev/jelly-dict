from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.dialog_shortcuts import install_standard_close_shortcut


UI_DIR = Path(__file__).resolve().parents[1] / "app" / "ui"


def test_standard_close_shortcut_uses_platform_close_sequence(qtbot):
    dialog = QtWidgets.QDialog()
    qtbot.addWidget(dialog)
    seen = []

    shortcut = install_standard_close_shortcut(dialog, lambda: seen.append("closed"))

    assert shortcut.key() == QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Close)
    assert shortcut.context() == QtCore.Qt.ShortcutContext.WindowShortcut

    shortcut.activated.emit()

    assert seen == ["closed"]


def test_all_app_dialogs_install_standard_close_shortcut():
    expected = {
        "entry_detail_dialog.py": 1,
        "entry_edit_dialog.py": 1,
        "duplicate_dialog.py": 1,
        "export_options_dialog.py": 1,
        "word_list_view.py": 1,
        "developer_tools_dialog.py": 1,
        "settings_view.py": 2,
    }

    for filename, expected_count in expected.items():
        source = (UI_DIR / filename).read_text(encoding="utf-8")
        if filename == "settings_view.py":
            source += "\n" + (UI_DIR / "settings_widgets.py").read_text(encoding="utf-8")

        assert source.count("install_standard_close_shortcut(self)") >= expected_count
