from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def test_duplicate_dialog_keeps_long_content_scrollable_and_actions_visible():
    script = r"""
from PySide6 import QtCore, QtWidgets

from app.core.models import Example, VocabularyEntry
from app.ui.duplicate_dialog import DuplicateDialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
existing = VocabularyEntry(
    language="en",
    word="<b>unsafe</b>",
    reading="<i>reading</i>",
    part_of_speech=["Noun"],
    meanings_summary="; ".join(f"meaning {idx}" for idx in range(30)),
    examples_flat=[
        Example(
            source_text_plain="<script>alert(1)</script>",
            translation_ko="번역",
        )
    ],
    synonyms=[f"syn-{idx}" for idx in range(12)],
    memo="<b>" + ("memo " * 80) + "</b>",
)
candidate = VocabularyEntry(
    language="en",
    word="<u>candidate</u>",
    reading="<em>new reading</em>",
    meanings_summary="<b>new meaning</b> " * 30,
    synonyms=["<mark>candidate-syn</mark>"],
    memo="<i>candidate memo</i> " * 80,
)

dialog = DuplicateDialog(existing, candidate)
dialog.resize(640, 300)
assert dialog.layout() is not None
dialog.layout().activate()

scroll = dialog.findChild(QtWidgets.QScrollArea, "duplicateScroll")
assert scroll is not None
assert scroll.widgetResizable()
assert scroll.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff
assert scroll.widget() is not None
assert scroll.widget().sizeHint().height() > scroll.viewport().height()

buttons = dialog.findChildren(QtWidgets.QPushButton, "duplicateOptionButton")
assert [button.text() for button in buttons] == [
    "기존 유지",
    "덮어쓰기",
    "예문/메모 병합",
    "새 항목으로 추가",
]
assert not scroll.findChildren(QtWidgets.QPushButton)
for button in buttons:
    assert not button.isHidden()
    bottom = button.mapTo(dialog, QtCore.QPoint(0, button.height())).y()
    assert bottom <= dialog.height()

labels = dialog.findChildren(QtWidgets.QLabel)
assert any("<b>unsafe</b>" in label.text() for label in labels)
assert any("<script>" in label.text() for label in labels)
assert any("<i>candidate memo</i>" in label.text() for label in labels)
assert any("<mark>candidate-syn</mark>" in label.text() for label in labels)
assert all(label.textFormat() == QtCore.Qt.PlainText for label in labels)

dialog.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
