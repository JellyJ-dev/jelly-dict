from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class PillScrollBar(QtWidgets.QScrollBar):
    """Scrollbar that paints its thumb as a true rounded pill.

    Qt stylesheets can leave square caps on macOS/offscreen styles, so the
    thumb is drawn directly while the native QScrollBar keeps interaction,
    wheel, and keyboard behavior.
    """

    def __init__(
        self,
        orientation: QtCore.Qt.Orientation,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self.setObjectName("pillScrollBar")
        self.setMouseTracking(True)
        self.setSingleStep(16)
        self.setPageStep(max(1, self.pageStep()))

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API
        if self.orientation() == QtCore.Qt.Vertical:
            return QtCore.QSize(12, 64)
        return QtCore.QSize(64, 12)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        if self.maximum() <= self.minimum():
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self._handle_color())
        rect = self._handle_rect()
        radius = min(rect.width(), rect.height()) / 2
        painter.drawRoundedRect(rect, radius, radius)

    def _handle_color(self) -> QtGui.QColor:
        if self.underMouse():
            return QtGui.QColor(148, 145, 136, 180)
        return QtGui.QColor(106, 105, 99, 148)

    def _handle_rect(self) -> QtCore.QRectF:
        vertical = self.orientation() == QtCore.Qt.Vertical
        length = self.height() if vertical else self.width()
        cross = self.width() if vertical else self.height()
        track_margin = 10
        track_length = max(1, length - (track_margin * 2))
        total = max(1, self.maximum() - self.minimum() + self.pageStep())
        thumb_length = max(44, int(track_length * self.pageStep() / total))
        thumb_length = min(track_length, thumb_length)
        travel = max(0, track_length - thumb_length)
        value_span = max(1, self.maximum() - self.minimum())
        offset = int(travel * (self.value() - self.minimum()) / value_span)
        thickness = min(7, max(6, cross - 5))
        cross_pos = (cross - thickness) / 2
        main_pos = track_margin + offset

        if vertical:
            return QtCore.QRectF(cross_pos, main_pos, thickness, thumb_length)
        return QtCore.QRectF(main_pos, cross_pos, thumb_length, thickness)


def install_pill_scrollbars(
    area: QtWidgets.QAbstractScrollArea,
    *,
    horizontal: bool = True,
    vertical: bool = True,
) -> None:
    if vertical:
        area.setVerticalScrollBar(PillScrollBar(QtCore.Qt.Vertical, area))
    if horizontal:
        area.setHorizontalScrollBar(PillScrollBar(QtCore.Qt.Horizontal, area))
