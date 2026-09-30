from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.word_input_parts.layout_constants import RESOURCE_DIR


def _resource_icon(name: str) -> QtGui.QIcon:
    return QtGui.QIcon(str(RESOURCE_DIR / "icons" / name))


def _repolish(widget: QtWidgets.QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class ElideLabel(QtWidgets.QLabel):
    def __init__(
        self,
        text: str = "",
        *,
        mode: QtCore.Qt.TextElideMode = QtCore.Qt.ElideMiddle,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self._mode = mode
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        super().setText(self._elided())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        super().setText(self._elided())

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API
        hint = super().sizeHint()
        if self._full_text:
            hint.setWidth(self.fontMetrics().horizontalAdvance(self._full_text) + 4)
        return hint

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def _elided(self) -> str:
        return self.fontMetrics().elidedText(
            self._full_text,
            self._mode,
            max(80, self.width()),
        )


class MenuTextButton(QtWidgets.QPushButton):
    def __init__(self, text: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._chevron_size = 8
        self._chevron_gap = 6
        self.setFixedHeight(34)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.icon = QtGui.QIcon()
        button_feature = getattr(QtWidgets.QStyleOptionButton, "ButtonFeature", None)
        has_menu = (
            getattr(button_feature, "HasMenu", None)
            if button_feature is not None
            else getattr(QtWidgets.QStyleOptionButton, "HasMenu", None)
        )
        if has_menu is not None:
            option.features &= ~has_menu
        self.style().drawControl(QtWidgets.QStyle.CE_PushButton, option, painter, self)

        font = QtGui.QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QtGui.QFont.Weight.Bold)
        metrics = QtGui.QFontMetricsF(font)
        text = self.text()
        text_width = math.ceil(metrics.horizontalAdvance(text))
        total_width = text_width + self._chevron_gap + self._chevron_size
        left = round((self.width() - total_width) / 2)
        center_y = self.height() / 2
        bounds = metrics.tightBoundingRect(text)
        baseline = center_y - (bounds.top() + bounds.bottom()) / 2
        color = QtGui.QColor("#d4cec4")
        if not self.isEnabled():
            color = QtGui.QColor("#6f6b64")
        elif self.underMouse():
            color = QtGui.QColor("#e7e1d6")
        painter.setPen(color)
        painter.setFont(font)
        painter.drawText(QtCore.QPointF(left, baseline), text)

        chevron_left = left + text_width + self._chevron_gap
        chevron_center_y = round(center_y + 0.5)
        pen = QtGui.QPen(color, 2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(
            chevron_left + 1,
            chevron_center_y - 2,
            chevron_left + self._chevron_size // 2,
            chevron_center_y + 2,
        )
        painter.drawLine(
            chevron_left + self._chevron_size - 1,
            chevron_center_y - 2,
            chevron_left + self._chevron_size // 2,
            chevron_center_y + 2,
        )
        painter.end()


class RightClickFilter(QtCore.QObject):
    rightClicked = QtCore.Signal()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.RightButton:
                self.rightClicked.emit()
                return True
        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            if event.button() == QtCore.Qt.LeftButton:
                self.rightClicked.emit()
                return True
        return super().eventFilter(obj, event)
