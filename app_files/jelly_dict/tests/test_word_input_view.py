from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.word_input_view import (
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
    WordInputView,
    split_bulk_input,
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
    assert not view.wordbook_search.isHidden()


def test_recent_search_filters_items_without_disabling_clear(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_recent([
        ("apple", "en", "사과", "recent"),
        ("banana", "en", "바나나", "recent"),
    ])

    view.wordbook_search.setText("banana")
    view._search_debounce.stop()
    view._render_current_list()

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == "[en] banana  —  바나나"
    assert view.clear_recent_btn.isEnabled()


def test_recent_search_empty_state_keeps_clear_available(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_recent([("apple", "en", "사과", "recent")])

    view.wordbook_search.setText("zzz")
    view._search_debounce.stop()
    view._render_current_list()

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == RECENT_FILTER_EMPTY_TEXT
    assert not _is_selectable(view.recent_list.item(0))
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


def test_switching_from_recent_to_wordbook_resets_search_context(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_recent([("apple", "en", "사과", "recent")])
    view.wordbook_search.setText("banana")

    view.set_wordbook("en", [("apple", "en", "", "사과")])

    assert view.wordbook_search.placeholderText() == "단어 / 뜻 검색..."
    assert view.wordbook_search.text() == ""
    assert view.recent_list.count() == 1


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


def test_split_bulk_input_uses_explicit_separators_only():
    assert split_bulk_input("apple, banana; cherry、月日") == [
        "apple",
        "banana",
        "cherry",
        "月日",
    ]
    assert split_bulk_input("ice cream") == ["ice cream"]
    assert split_bulk_input("apple, Apple, banana") == ["apple", "banana"]


def test_bulk_input_submission_uses_bulk_signal(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    seen = []
    view.bulkSubmitted.connect(lambda words, lang: seen.append((words, lang)))

    view.input.setText("apple, banana")
    view._submit()

    assert seen == [(["apple", "banana"], "")]


def test_bulk_input_updates_lookup_button_label(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    view.input.setText("apple, banana")

    assert view.lookup_btn.text() == "일괄 조회"


def test_trailing_bulk_separator_submits_clean_single_word(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    seen = []
    view.submitted.connect(lambda word, lang: seen.append((word, lang)))

    view.input.setText("apple,")
    view._submit()

    assert seen == [("apple", "")]


def test_long_ocr_and_queue_chips_are_elided(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    long_token = "extraordinarily-long-token-that-should-not-stretch-the-panel"

    view.set_ocr_tokens([long_token])
    view.set_lookup_queue([
        (long_token, "pending", "job-1"),
        (long_token, "failed", "job-2"),
    ])

    ocr_chip = view._ocr_chip_buttons[long_token]
    queue_texts = [
        button.text()
        for button in view.queue_chips_frame.findChildren(QtWidgets.QPushButton)
    ]
    assert "…" in ocr_chip.text()
    assert all("…" in text for text in queue_texts)
    assert long_token in ocr_chip.toolTip()
