from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.word_input_view import (
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
    WordInputView,
    split_bulk_input,
)
from app.ui.widgets.wordbook_items import WordbookDisplayItem
from app.ui.widgets.wordbook_row import WordbookRow


def _is_selectable(item) -> bool:
    return bool(item.flags() & QtCore.Qt.ItemIsSelectable)


def _key_event(
    key: QtCore.Qt.Key,
    modifiers: QtCore.Qt.KeyboardModifier | QtCore.Qt.KeyboardModifiers = (
        QtCore.Qt.KeyboardModifier.NoModifier
    ),
) -> QtGui.QKeyEvent:
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, modifiers)


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


def test_wordbook_search_matches_hidden_metadata_without_extra_row_ui(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "en",
        [
            WordbookDisplayItem(
                "apple",
                "en",
                "",
                "사과",
                tags=("exam", "fruit"),
                memo="중요 단어",
                examples=("An apple a day keeps the doctor away 사과 하나",),
            ),
            WordbookDisplayItem("banana", "en", "", "바나나"),
        ],
    )

    view.wordbook_search.setText("exam 중요")
    view._search_debounce.stop()
    view._render_wordbook()

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).data(QtCore.Qt.UserRole) == ("apple", "en")
    assert view.recent_list.item(0).sizeHint().height() == 62
    row = view.recent_list.itemWidget(view.recent_list.item(0))
    assert isinstance(row, WordbookRow)
    assert len(view.recent_list.findChildren(WordbookRow)) == 1
    assert row.findChildren(QtWidgets.QLabel, "wordbookWord")
    assert not row.findChildren(QtWidgets.QLabel, "wordbookBadge")


def test_wordbook_search_matches_example_only_text(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "en",
        [
            WordbookDisplayItem(
                "apple",
                "en",
                "",
                "사과",
                examples=("orchard sentence only appears here",),
            ),
            WordbookDisplayItem("banana", "en", "", "바나나"),
        ],
    )

    view.wordbook_search.setText("orchard")
    view._search_debounce.stop()
    view._render_wordbook()

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).data(QtCore.Qt.UserRole) == ("apple", "en")


def test_wordbook_search_does_not_match_language_code_for_every_row(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "en",
        [
            WordbookDisplayItem("apple", "en", "", "사과"),
            WordbookDisplayItem("banana", "en", "", "바나나"),
        ],
    )

    view.wordbook_search.setText("en")
    view._search_debounce.stop()
    view._render_wordbook()

    assert view.recent_list.count() == 1
    assert view.recent_list.item(0).text() == WORDBOOK_FILTER_EMPTY_TEXT


def test_wordbook_tooltip_exposes_metadata_without_visible_badges(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "ja",
        [
            WordbookDisplayItem(
                "月日",
                "ja",
                "つきひ",
                "세월",
                tags=("review",),
                memo="시험 전 복습",
                examples=("月日が流れる 시간이 흐른다",),
                updated_at="2026-05-31T12:00:00+00:00",
            )
        ],
    )

    tooltip = view.recent_list.item(0).toolTip()

    assert "月日" in tooltip
    assert "つきひ" in tooltip
    assert "태그: review" in tooltip
    assert "메모: 시험 전 복습" in tooltip
    assert "예문 1개:" in tooltip
    assert "수정: 2026-05-31" in tooltip
    row = view.recent_list.itemWidget(view.recent_list.item(0))
    assert isinstance(row, WordbookRow)
    assert not row.findChildren(QtWidgets.QLabel, "wordbookBadge")


def test_wordbook_row_actions_handle_selected_words_without_header_growth(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    edit_seen = []
    delete_seen = []
    view.wordbookEditRequested.connect(lambda lang, word: edit_seen.append((lang, word)))
    view.wordbookDeleteRequested.connect(
        lambda lang, words: delete_seen.append((lang, words))
    )
    view.set_wordbook(
        "en",
        [
            ("apple", "en", "", "사과"),
            ("banana", "en", "", "바나나"),
        ],
    )

    assert not hasattr(view, "wordbook_select_visible_btn")
    assert view.wordbook_delete_btn.isHidden()
    assert not hasattr(view, "wordbook_copy_btn")
    first_item = view.recent_list.item(0)
    first_row = view.recent_list.itemWidget(first_item)
    assert isinstance(first_row, WordbookRow)
    assert first_row.action_bar.isHidden()

    view.recent_list.setCurrentItem(first_item)
    first_item.setSelected(True)

    assert view.wordbook_stats.text() == "2/2개 · 선택 1개"
    assert view.wordbook_delete_btn.isHidden()
    assert not first_row.action_bar.isHidden()

    first_row.edit_button.click()
    assert edit_seen == [("en", "apple")]

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_A, QtCore.Qt.KeyboardModifier.ControlModifier),
    )
    second_item = view.recent_list.item(1)
    second_row = view.recent_list.itemWidget(second_item)
    assert isinstance(second_row, WordbookRow)

    assert view.wordbook_stats.text() == "2/2개 · 선택 2개"
    assert view.wordbook_delete_btn.isHidden()
    assert not first_row.action_bar.isHidden()
    assert second_row.action_bar.isHidden()

    first_row.edit_button.click()
    assert edit_seen[-1] == ("en", "apple")

    first_row.delete_button.click()
    assert delete_seen == [("en", ["apple", "banana"])]

    view.recent_list.setCurrentItem(second_item)

    assert first_row.action_bar.isHidden()
    assert not second_row.action_bar.isHidden()


def test_wordbook_keyboard_shortcuts_reuse_row_actions_without_header_growth(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    delete_seen = []
    view.wordbookDeleteRequested.connect(
        lambda lang, words: delete_seen.append((lang, words))
    )
    view.set_wordbook(
        "en",
        [
            ("apple", "en", "", "사과"),
            ("banana", "en", "", "바나나"),
        ],
    )
    first_item = view.recent_list.item(0)
    view.recent_list.setCurrentItem(first_item)
    first_item.setSelected(True)

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_C, QtCore.Qt.KeyboardModifier.ControlModifier)
    )
    assert view.status_summary.text() == "선택한 단어 1개 복사됨"

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_Delete),
    )
    assert delete_seen == [("en", ["apple"])]

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_A, QtCore.Qt.KeyboardModifier.ControlModifier)
    )
    assert view.wordbook_stats.text() == "2/2개 · 선택 2개"
    assert view.wordbook_delete_btn.isHidden()


def test_wordbook_keyboard_shortcuts_do_not_intercept_recent_list(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_recent([("apple", "en", "사과", "recent")])
    status_before = view.status_summary.text()

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_C, QtCore.Qt.KeyboardModifier.ControlModifier)
    )
    assert view.status_summary.text() == status_before


def test_list_return_opens_current_visible_entry(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    opened = []
    view.recentEntryRequested.connect(lambda word, lang: opened.append((word, lang)))
    view.set_recent([("apple", "en", "사과", "recent")])

    view.recent_list.setCurrentItem(view.recent_list.item(0))
    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_Return),
    )

    assert opened == [("apple", "en")]


def test_search_return_opens_first_visible_wordbook_entry(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    opened = []
    view.recentEntryRequested.connect(lambda word, lang: opened.append((word, lang)))
    view.set_wordbook(
        "en",
        [
            ("apple", "en", "", "사과"),
            ("banana", "en", "", "바나나"),
        ],
    )
    view.recent_list.setCurrentItem(view.recent_list.item(1))
    view.wordbook_search.setText("banana")

    QtWidgets.QApplication.sendEvent(
        view.wordbook_search,
        _key_event(QtCore.Qt.Key_Return),
    )

    assert opened == [("banana", "en")]


def test_search_return_does_not_open_stale_item_when_filter_has_no_results(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    opened = []
    view.recentEntryRequested.connect(lambda word, lang: opened.append((word, lang)))
    view.set_wordbook(
        "en",
        [
            ("apple", "en", "", "사과"),
            ("banana", "en", "", "바나나"),
        ],
    )
    view.recent_list.setCurrentItem(view.recent_list.item(0))
    view.wordbook_search.setText("zzz")

    QtWidgets.QApplication.sendEvent(
        view.wordbook_search,
        _key_event(QtCore.Qt.Key_Return),
    )

    assert opened == []
    assert view.recent_list.item(0).text() == WORDBOOK_FILTER_EMPTY_TEXT


def test_modified_return_does_not_open_list_entry(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    opened = []
    view.recentEntryRequested.connect(lambda word, lang: opened.append((word, lang)))
    view.set_recent([("apple", "en", "사과", "recent")])
    view.recent_list.setCurrentItem(view.recent_list.item(0))

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_Return, QtCore.Qt.KeyboardModifier.ControlModifier),
    )

    assert opened == []


def test_keypad_return_opens_list_entry(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    opened = []
    view.recentEntryRequested.connect(lambda word, lang: opened.append((word, lang)))
    view.set_recent([("apple", "en", "사과", "recent")])
    view.recent_list.setCurrentItem(view.recent_list.item(0))

    QtWidgets.QApplication.sendEvent(
        view.recent_list,
        _key_event(QtCore.Qt.Key_Enter, QtCore.Qt.KeyboardModifier.KeypadModifier),
    )

    assert opened == [("apple", "en")]


def test_search_escape_clears_filter_without_header_growth(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "en",
        [
            ("apple", "en", "", "사과"),
            ("banana", "en", "", "바나나"),
        ],
    )
    view.wordbook_search.setText("banana")
    view._search_debounce.stop()
    view._render_wordbook()

    QtWidgets.QApplication.sendEvent(
        view.wordbook_search,
        _key_event(QtCore.Qt.Key_Escape),
    )

    assert view.wordbook_search.text() == ""
    assert view.recent_list.count() == 2
    assert view.wordbook_stats.text() == "2/2개"
    assert view.wordbook_delete_btn.isHidden()


def test_search_escape_without_filter_is_not_consumed(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook("en", [("apple", "en", "", "사과")])

    assert not view.eventFilter(view.wordbook_search, _key_event(QtCore.Qt.Key_Escape))


def test_search_down_focuses_first_visible_result(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "en",
        [
            ("apple", "en", "", "사과"),
            ("banana", "en", "", "바나나"),
        ],
    )
    view.recent_list.setCurrentItem(view.recent_list.item(0))
    view.wordbook_search.setText("banana")

    QtWidgets.QApplication.sendEvent(
        view.wordbook_search,
        _key_event(QtCore.Qt.Key_Down),
    )

    assert view.recent_list.currentItem().data(QtCore.Qt.UserRole) == ("banana", "en")
    assert view.recent_list.currentItem().isSelected()
    assert view.wordbook_stats.text() == "1/2개 · 선택 1개"


def test_wordbook_selection_keeps_row_size_and_header_actions_stable(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook(
        "ja",
        [
            ("粗製乱造", "ja", "そせいらんぞう", "조제 남조"),
            ("月日", "ja", "つきひ", "세월"),
        ],
    )

    item = view.recent_list.item(0)
    initial_size = item.sizeHint()

    view.recent_list.setCurrentItem(item)
    item.setSelected(True)

    assert item.sizeHint() == initial_size
    assert item.sizeHint().height() == 62
    assert view.wordbook_delete_btn.isHidden()


def test_wordbook_row_actions_align_to_card_edge_when_visible(qtbot):
    row = WordbookRow("en", "characteristically", "", "특징적으로")
    qtbot.addWidget(row)
    row.resize(1126, 46)
    row.set_actions_visible(True)
    row._place_action_bar()

    assert not row.action_bar.isHidden()
    assert row.action_bar.geometry().right() >= row.width() - 20


def test_wordbook_expand_switches_to_real_wide_panel_mode(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_wordbook("ja", [("粗製乱造", "ja", "そせいらんぞう", "조제 남조")])

    assert view.wordbook_expand_btn.text() == "확대"
    assert view.recent_panel.maximumWidth() == 980

    view._toggle_wordbook_expanded()

    assert view.wordbook_expand_btn.text() == "축소"
    assert view.recent_panel.property("expanded") is True
    assert view.recent_panel.maximumWidth() > 980
    assert view._root_layout.contentsMargins().left() == 36


def test_switching_from_recent_to_wordbook_resets_search_context(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)
    view.set_recent([("apple", "en", "사과", "recent")])
    view.wordbook_search.setText("banana")

    view.set_wordbook("en", [("apple", "en", "", "사과")])

    assert view.wordbook_search.placeholderText() == "단어 / 뜻 / 태그 / 메모 검색..."
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


def test_footer_status_summary_has_room_for_language_paths(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    assert view.status_summary.minimumWidth() >= 480
    assert view.status_summary.maximumWidth() >= 760
    assert view.status_summary.sizePolicy().horizontalPolicy() == (
        QtWidgets.QSizePolicy.Preferred
    )


def test_detection_status_renders_in_footer_not_command_panel(qtbot):
    view = WordInputView()
    qtbot.addWidget(view)

    view.set_status_summary("EN: vocab_en.xlsx · JA: vocab_ja.xlsx · Naver · cache on")
    view.set_detection_label("감지된 언어: en (캐시)")

    assert "감지: en (캐시)" in view.status_summary.text()
    assert not hasattr(view, "detected_label")
