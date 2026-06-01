from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.services.export_preflight import PreflightResult
from app.storage.settings_store import Settings, SettingsStore
from app.ui.dialog_buttons import (
    FOOTER_BUTTON_MIN_HEIGHT,
    FOOTER_BUTTON_MIN_WIDTH,
    PRIMARY_BUTTON_NAME,
    SECONDARY_BUTTON_NAME,
)
from app.ui.export_options import build_export_plan
from app.ui.export_options_dialog import ExportOptionsDialog
from app.ui.settings_view import SettingsDialog


def _button_by_text(widget: QtWidgets.QWidget, text: str) -> QtWidgets.QPushButton:
    return next(
        button for button in widget.findChildren(QtWidgets.QPushButton) if button.text() == text
    )


def _assert_footer_button_contract(
    button: QtWidgets.QPushButton,
    *,
    object_name: str,
    min_width: int = FOOTER_BUTTON_MIN_WIDTH,
) -> None:
    assert button.objectName() == object_name
    assert button.minimumHeight() == FOOTER_BUTTON_MIN_HEIGHT
    assert button.minimumWidth() >= min_width
    assert button.maximumWidth() > button.minimumWidth()
    assert button.cursor().shape() == QtCore.Qt.PointingHandCursor


def test_settings_dialog_footer_buttons_use_shared_contract(qtbot, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(store, initial_settings=store.load())
    qtbot.addWidget(dialog)

    _assert_footer_button_contract(
        _button_by_text(dialog, "저장"),
        object_name=PRIMARY_BUTTON_NAME,
    )
    _assert_footer_button_contract(
        _button_by_text(dialog, "취소"),
        object_name=SECONDARY_BUTTON_NAME,
    )
    dialog._wait_for_status_probe()


def test_export_dialog_footer_buttons_use_shared_contract(qtbot, tmp_path):
    plan = build_export_plan(
        Settings(),
        language="en",
        deck_name="JellyDict::EN",
        card_count=10,
    )
    dialog = ExportOptionsDialog(
        plan=plan,
        output_path=tmp_path / "out.apkg",
        preflight=PreflightResult(()),
    )
    qtbot.addWidget(dialog)

    _assert_footer_button_contract(
        _button_by_text(dialog, "내보내기"),
        object_name=PRIMARY_BUTTON_NAME,
        min_width=82,
    )
    _assert_footer_button_contract(
        _button_by_text(dialog, "상세 설정"),
        object_name=SECONDARY_BUTTON_NAME,
        min_width=88,
    )
    _assert_footer_button_contract(
        _button_by_text(dialog, "취소"),
        object_name=SECONDARY_BUTTON_NAME,
    )
