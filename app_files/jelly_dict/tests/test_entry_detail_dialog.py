from __future__ import annotations

from PySide6 import QtWidgets

from app.core.models import Example, VocabularyEntry
from app.ui.entry_detail_dialog import EntryDetailDialog


def _label_texts(dialog: EntryDetailDialog) -> list[str]:
    return [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]


def test_entry_detail_shows_memo_tags_source_and_all_examples(qtbot):
    entry = VocabularyEntry(
        language="en",
        word="retention",
        meanings_summary="1.보유",
        tags=["school", "exam"],
        memo="중요 단어",
        source_url="https://example.test/retention",
        examples_flat=[
            Example(source_text_plain=f"example {idx}", translation_ko=f"예문 {idx}")
            for idx in range(6)
        ],
    )
    dialog = EntryDetailDialog(entry)
    qtbot.addWidget(dialog)

    texts = _label_texts(dialog)

    assert "태그" in texts
    assert "school, exam" in texts
    assert "메모" in texts
    assert "중요 단어" in texts
    assert "출처" in texts
    assert any("https://example.test/retention" in text for text in texts)
    assert "example 5\n예문 5" in texts


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
