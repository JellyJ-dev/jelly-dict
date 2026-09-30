from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets


def install_standard_close_shortcut(
    dialog: QtWidgets.QDialog,
    close_slot: Callable[[], object] | None = None,
) -> QtGui.QShortcut:
    """Install the platform-standard dialog close shortcut.

    Qt maps QKeySequence.Close to Command+W on macOS and Ctrl+W elsewhere.
    """
    shortcut = QtGui.QShortcut(
        QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Close),
        dialog,
    )
    shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
    shortcut.activated.connect(close_slot or dialog.close)
    dialog.close_shortcut = shortcut  # type: ignore[attr-defined]
    return shortcut
