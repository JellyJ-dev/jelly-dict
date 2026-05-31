from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.widgets.anki_export_button import AnkiExportButton


def test_anki_export_button_uses_shared_wordbook_header_style_names(qtbot):
    button = AnkiExportButton()
    qtbot.addWidget(button)

    assert button.objectName() == "wordbookExportShell"
    assert button.main_button.objectName() == "wordbookExportButton"
    assert button.option_button.objectName() == "wordbookExportOptionButton"
    assert button.findChild(QtWidgets.QFrame, "wordbookExportDivider") is not None
    assert not button.main_button.icon().isNull()
    assert button.main_button.iconSize() == QtCore.QSize(18, 18)
    assert not button.main_button.icon().pixmap(18, 18).isNull()


def test_anki_export_button_switches_to_active_icon(qtbot):
    button = AnkiExportButton()
    qtbot.addWidget(button)
    normal_key = button.main_button.icon().cacheKey()

    button._set_active(True)

    assert button.main_button.icon().cacheKey() != normal_key
    assert not button.main_button.icon().pixmap(18, 18).isNull()

    button._set_active(False)

    assert button.main_button.icon().cacheKey() == normal_key
