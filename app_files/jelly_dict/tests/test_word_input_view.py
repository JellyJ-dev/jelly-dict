from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.word_input_view import (
    RECENT_EMPTY_TEXT,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
    WordInputView,
)


def _is_selectable(item) -> bool:
    return bool(item.flags() & QtCore.Qt.ItemIsSelectable)


def test_recent_empty_state_disables_clear_action(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    view.set_recent([])

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == RECENT_EMPTY_TEXT
    assert not _is_selectable(view.recent_list.item(0))
    assert not view.clear_recent_btn.isEnabled()


def test_recent_items_enable_clear_action(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    view.set_recent([("apple", "en", "사과", "recent")])

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == "[en] apple  —  사과"
    assert _is_selectable(view.recent_list.item(0))
    assert view.clear_recent_btn.isEnabled()


def test_wordbook_empty_state_disables_export_and_delete(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    view.set_wordbook("en", [])

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == WORDBOOK_EMPTY_TEXT
    assert not _is_selectable(view.recent_list.item(0))
    assert not view.wordbook_export_btn.isEnabled()
    assert not view.wordbook_delete_btn.isEnabled()


def test_wordbook_filter_empty_state_preserves_export(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook("en", [("apple", "en", "", "사과")])

    view.wordbook_search.setText("banana")
    view._search_debounce.stop()
    view._render_wordbook()

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == WORDBOOK_FILTER_EMPTY_TEXT
    assert not _is_selectable(view.recent_list.item(0))
    assert view.wordbook_export_btn.isEnabled()
    assert not view.wordbook_delete_btn.isEnabled()


def test_lookup_queue_status_labels_avoid_emoji_glyph_dependency(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    view.set_lookup_queue([
        ("apple", "running", "job-1"),
        ("banana", "pending", "job-2"),
        ("cherry", "failed", "job-3"),
    ])

    chips = [
        button.text()
        for button in view.queue_chips_frame.findChildren(QtWidgets.QPushButton)
    ]

    assert "진행 · apple" in chips
    assert "banana" in chips
    assert "실패 · cherry" in chips
