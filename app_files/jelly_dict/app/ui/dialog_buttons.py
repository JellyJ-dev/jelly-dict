from __future__ import annotations

from PySide6 import QtCore, QtWidgets


PRIMARY_BUTTON_NAME = "settingsPrimaryButton"
SECONDARY_BUTTON_NAME = "settingsSecondaryButton"
FOOTER_BUTTON_MIN_HEIGHT = 40
FOOTER_BUTTON_MIN_WIDTH = 64


def configure_footer_button(
    button: QtWidgets.QPushButton,
    *,
    role: str,
    text: str | None = None,
    min_width: int = FOOTER_BUTTON_MIN_WIDTH,
) -> QtWidgets.QPushButton:
    if text is not None:
        button.setText(text)
    button.setObjectName(PRIMARY_BUTTON_NAME if role == "primary" else SECONDARY_BUTTON_NAME)
    button.setCursor(QtCore.Qt.PointingHandCursor)
    button.setMinimumSize(min_width, FOOTER_BUTTON_MIN_HEIGHT)
    button.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
    return button
