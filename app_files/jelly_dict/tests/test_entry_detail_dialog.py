from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.core.models import Example, VocabularyEntry
from app.ui.entry_detail_dialog import EntryDetailDialog


def _label_texts(dialog: EntryDetailDialog) -> list[str]:
    return [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]


def test_entry_detail_shows_memo_tags_source_and_all_examples(qtbot):
    entry = VocabularyEntry(
        language="en",
        word="retention",
        meanings_summary="1.보유",
        tags=["school", "<b>exam</b>"],
        memo="중요 <b>단어</b>",
        source_url="https://example.test/retention?from=very-long-query",
        examples_flat=[
            Example(source_text_plain=f"example {idx}", translation_ko=f"예문 {idx}")
            for idx in range(12)
        ],
    )
    dialog = EntryDetailDialog(entry)
    qtbot.addWidget(dialog)

    texts = _label_texts(dialog)

    assert "태그" in texts
    assert "school, <b>exam</b>" in texts
    assert "메모" in texts
    assert "중요 <b>단어</b>" in texts
    assert "출처" in texts
    assert any("example.test/retention" in text for text in texts)
    example_rows = [text for text in texts if text.startswith("example ")]
    assert len(example_rows) == 12
    assert "example 11\n예문 11" in texts
    plain_labels = [
        label
        for label in dialog.findChildren(QtWidgets.QLabel)
        if label.text() in {"school, <b>exam</b>", "중요 <b>단어</b>"}
    ]
    assert plain_labels
    assert all(label.textFormat() == QtCore.Qt.PlainText for label in plain_labels)


def test_entry_detail_word_list_reports_hidden_count(qtbot):
    entry = VocabularyEntry(
        language="en",
        word="sample",
        meanings_summary="1.예시",
        synonyms=[f"syn-{idx}" for idx in range(22)],
    )
    dialog = EntryDetailDialog(entry)
    qtbot.addWidget(dialog)

    texts = _label_texts(dialog)

    assert any("외 2개" in text for text in texts)


def test_entry_detail_preserves_full_word_when_title_uses_primary_form(qtbot):
    entry = VocabularyEntry(
        language="ja",
        word="月日・歳月",
        meanings_summary="1.세월",
    )
    dialog = EntryDetailDialog(entry)
    qtbot.addWidget(dialog)

    texts = _label_texts(dialog)

    assert "月日" in texts
    assert "月日・歳月" in texts
