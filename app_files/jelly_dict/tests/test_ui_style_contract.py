from __future__ import annotations

from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "app" / "ui" / "resources" / "theme.qss"
WORD_LIST_VIEW = Path(__file__).resolve().parents[1] / "app" / "ui" / "word_list_view.py"


def test_button_text_alignment_contract():
    qss = THEME.read_text(encoding="utf-8")

    assert "QPushButton {" in qss
    assert "text-align: center;" in qss
    assert "text-align: left;" not in qss


def test_word_list_dialog_button_text_alignment_contract():
    source = WORD_LIST_VIEW.read_text(encoding="utf-8")

    assert "QPushButton {" in source
    assert "text-align: center;" in source
    assert "text-align: left;" not in source
