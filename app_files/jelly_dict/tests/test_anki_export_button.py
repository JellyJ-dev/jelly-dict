from __future__ import annotations

from PySide6 import QtWidgets

from app.ui.widgets.anki_export_button import AnkiExportButton


def test_anki_export_button_uses_shared_wordbook_header_style_names(qtbot):
    button = AnkiExportButton()
    qtbot.addWidget(button)

    assert button.objectName() == "wordbookExportShell"
    assert button.main_button.objectName() == "wordbookExportButton"
    assert button.option_button.objectName() == "wordbookExportOptionButton"
    assert button.findChild(QtWidgets.QFrame, "wordbookExportDivider") is not None
