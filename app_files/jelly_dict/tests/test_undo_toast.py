from __future__ import annotations

from PySide6 import QtWidgets

from app.ui.widgets.undo_toast import UndoToast


def test_undo_toast_shows_compact_message_and_runs_callback(qtbot):
    parent = QtWidgets.QWidget()
    parent.resize(640, 480)
    qtbot.addWidget(parent)
    toast = UndoToast(parent)
    seen = []

    toast.show_message("2개를 삭제했습니다.", lambda: seen.append("undo"))

    assert not toast.isHidden()
    assert toast.message_label.text() == "2개를 삭제했습니다."
    assert toast._dismiss_timer.interval() == 3000
    assert toast.width() <= 380

    toast.undo_button.click()

    assert seen == ["undo"]
    assert not toast.isVisible()


def test_undo_toast_supports_keyboard_trigger_after_hiding(qtbot):
    parent = QtWidgets.QWidget()
    parent.resize(640, 480)
    qtbot.addWidget(parent)
    toast = UndoToast(parent)
    seen = []

    toast.show_message("1개를 삭제했습니다.", lambda: seen.append("undo"))
    toast.hide()
    toast.trigger_undo()

    assert seen == ["undo"]
