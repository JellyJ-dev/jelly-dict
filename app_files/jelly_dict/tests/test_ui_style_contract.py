from __future__ import annotations

from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "app" / "ui" / "resources" / "theme.qss"


def test_button_text_alignment_contract():
    qss = THEME.read_text(encoding="utf-8")

    assert "QPushButton {" in qss
    assert "text-align: center;" in qss
    assert "text-align: left;" not in qss
