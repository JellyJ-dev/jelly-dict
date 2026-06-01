from __future__ import annotations

from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "app" / "ui" / "resources" / "theme.qss"
WORD_LIST_VIEW = Path(__file__).resolve().parents[1] / "app" / "ui" / "word_list_view.py"
WORD_INPUT_VIEW = Path(__file__).resolve().parents[1] / "app" / "ui" / "word_input_view.py"
WORDBOOK_ROW = (
    Path(__file__).resolve().parents[1] / "app" / "ui" / "widgets" / "wordbook_row.py"
)
MAIN_WINDOW = Path(__file__).resolve().parents[1] / "app" / "ui" / "main_window.py"


def _qss_block(qss: str, selector: str) -> str:
    return qss.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_button_text_alignment_contract():
    qss = THEME.read_text(encoding="utf-8")

    assert "QPushButton {" in qss
    assert "text-align: center;" in qss
    assert "text-align: left;" not in qss
    assert "text-align: center;" in _qss_block(qss, "QPushButton#settingsPrimaryButton")
    assert "text-align: center;" in _qss_block(qss, "QPushButton#settingsSecondaryButton")


def test_wordbook_header_controls_share_transparent_surface_contract():
    qss = THEME.read_text(encoding="utf-8")

    export_shell = _qss_block(qss, "QWidget#wordbookExportShell")
    export_active = _qss_block(qss, 'QWidget#wordbookExportShell[active="true"]')
    export_button = _qss_block(qss, "QPushButton#wordbookExportButton")
    divider = _qss_block(qss, "QFrame#wordbookExportDivider")

    assert "background: transparent;" in export_shell
    assert "border: 1px solid transparent;" in export_shell
    assert "border-color: #3f3f3c;" in export_active
    assert "font-size: 13px;" in export_button
    assert "text-align: center;" in export_button
    assert "background: transparent;" in divider


def test_settings_combo_popup_uses_rounded_dark_menu_contract():
    qss = THEME.read_text(encoding="utf-8")

    popup = _qss_block(qss, "QComboBox#settingsCombo QAbstractItemView")
    item = _qss_block(qss, "QComboBox#settingsCombo QAbstractItemView::item")
    selected = _qss_block(qss, "QComboBox#settingsCombo QAbstractItemView::item:selected")

    assert "border: 1px solid #454542;" in popup
    assert "border-radius: 11px;" in popup
    assert "padding: 6px;" in popup
    assert "selection-background-color: #3a322d;" in popup
    assert "border-radius: 8px;" in item
    assert "background: #3a322d;" in selected


def test_scrollbars_use_rounded_pill_contract():
    qss = THEME.read_text(encoding="utf-8")

    scrollbar = _qss_block(qss, "QScrollBar:vertical")
    handle = _qss_block(qss, "QScrollBar::handle:vertical")
    settings_scrollbar = _qss_block(qss, "QDialog#settingsDialog QScrollBar:vertical")
    settings_handle = _qss_block(qss, "QDialog#settingsDialog QScrollBar::handle:vertical")

    assert "width: 14px;" in scrollbar
    assert "border-radius: 8px;" in scrollbar
    assert "border: 2px solid transparent;" in handle
    assert "border-radius: 7px;" in handle
    assert "background: transparent;" in settings_scrollbar
    assert "border-radius: 8px;" in settings_scrollbar
    assert "border-radius: 7px;" in settings_handle


def test_delete_undo_toast_uses_compact_translucent_contract():
    qss = THEME.read_text(encoding="utf-8")

    toast = _qss_block(qss, "QFrame#undoToast")
    button = _qss_block(qss, "QPushButton#undoToastButton")

    assert "rgba(36, 36, 34" in toast
    assert "border-radius: 16px;" in toast
    assert "max-height: 28px;" in button
    assert "text-align: center;" in button


def test_wordbook_row_actions_are_edit_delete_only_contract():
    input_source = WORD_INPUT_VIEW.read_text(encoding="utf-8")
    row_source = WORDBOOK_ROW.read_text(encoding="utf-8")

    assert "wordbookEditRequested" in input_source
    assert "wordbookRequeryRequested" not in input_source
    assert "wordbook_copy_btn" not in input_source
    assert 'self._action_button("수정"' in row_source
    assert 'self._action_button("복사"' not in row_source
    assert 'self._action_button("재조회"' not in row_source


def test_main_menu_avoids_native_edit_menu_injections():
    source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert 'menu.addMenu("도구")' in source
    assert 'menu.addMenu("편집")' not in source


def test_word_list_dialog_button_text_alignment_contract():
    source = WORD_LIST_VIEW.read_text(encoding="utf-8")

    assert "QPushButton {" in source
    assert "text-align: center;" in source
    assert "text-align: left;" not in source
    assert "QComboBox#wordListSort QAbstractItemView" in source
    assert "border-radius: 11px;" in source
    assert "selection-background-color: #3a322d;" in source
