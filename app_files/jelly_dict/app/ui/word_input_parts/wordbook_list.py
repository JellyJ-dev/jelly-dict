from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.widgets.pill_scrollbar import PillScrollBar


class WordbookListWidget(QtWidgets.QListWidget):
    """Trackpad-friendly scrolling for the wordbook list."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_remainder = 0.0
        self._pending_deselect_item: QtWidgets.QListWidgetItem | None = None
        self._deselect_timer = QtCore.QTimer(self)
        self._deselect_timer.setSingleShot(True)
        self._deselect_timer.timeout.connect(self._apply_pending_deselect)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBar(PillScrollBar(QtCore.Qt.Vertical, self))
        self.verticalScrollBar().setSingleStep(16)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self._cancel_pending_deselect()
        if (
            event.button() == QtCore.Qt.LeftButton
            and self.selectionMode() == QtWidgets.QAbstractItemView.ExtendedSelection
            and self._is_plain_click(event)
        ):
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.isSelected():
                self._pending_deselect_item = item
                self._deselect_timer.start(QtWidgets.QApplication.doubleClickInterval() + 40)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        self._cancel_pending_deselect()
        if (
            event.button() == QtCore.Qt.LeftButton
            and self.selectionMode() == QtWidgets.QAbstractItemView.ExtendedSelection
            and self._is_plain_click(event)
        ):
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentItem(item)
                item.setSelected(True)
                self.itemDoubleClicked.emit(item)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        bar = self.verticalScrollBar()
        pixel_y = event.pixelDelta().y()
        if pixel_y:
            self._scroll_by(pixel_y * 0.62)
            event.accept()
            return
        angle_y = event.angleDelta().y()
        if angle_y:
            self._scroll_by((angle_y / 120.0) * bar.singleStep() * 2.2)
            event.accept()
            return
        super().wheelEvent(event)

    def _scroll_by(self, delta: float) -> None:
        bar = self.verticalScrollBar()
        self._wheel_remainder += delta
        whole_delta = int(self._wheel_remainder)
        if whole_delta == 0:
            return
        self._wheel_remainder -= whole_delta
        bar.setValue(bar.value() - whole_delta)

    @staticmethod
    def _is_plain_click(event: QtGui.QMouseEvent) -> bool:
        modifiers = event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier
        return modifiers == QtCore.Qt.KeyboardModifier.NoModifier

    def _cancel_pending_deselect(self) -> None:
        self._deselect_timer.stop()
        self._pending_deselect_item = None

    def _apply_pending_deselect(self) -> None:
        item = self._pending_deselect_item
        self._pending_deselect_item = None
        if item is None or self.row(item) < 0 or not item.isSelected():
            return
        item.setSelected(False)
