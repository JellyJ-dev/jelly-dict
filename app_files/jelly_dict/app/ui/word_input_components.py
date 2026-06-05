from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.widgets.pill_scrollbar import PillScrollBar

NORMAL_LIST_HEIGHT = 348
ROOT_MARGIN_NORMAL = (64, 8, 64, 16)
ROOT_MARGIN_EXPANDED = (36, 14, 36, 16)
HERO_TO_WORDBOOK_SPACING = 4
ROOT_LAYOUT_SPACING = 6
RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources"
RECENT_EMPTY_TEXT = "최근 기록 없음"
RECENT_FILTER_EMPTY_TEXT = "검색 결과 없음"
WORDBOOK_EMPTY_TEXT = "저장된 단어 없음"
WORDBOOK_FILTER_EMPTY_TEXT = "검색 결과 없음"
BULK_INPUT_SPLIT_RE = re.compile(r"[\r\n,;，、]+")


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
        font_metrics = QtGui.QFontMetricsF(font)
        text = self.text()
        text_width = math.ceil(font_metrics.horizontalAdvance(text))
        total_width = text_width + self._chevron_gap + self._chevron_size
        left = round((self.width() - total_width) / 2)
        center_y = self.height() / 2
        text_bounds = font_metrics.tightBoundingRect(text)
        baseline = center_y - (text_bounds.top() + text_bounds.bottom()) / 2

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


class OcrCandidateChip(QtWidgets.QPushButton):
    doubleClicked = QtCore.Signal()
    rightClicked = QtCore.Signal()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.RightButton:
            self.rightClicked.emit()
        super().mousePressEvent(event)


class QueueJobChip(QtWidgets.QPushButton):
    rightClicked = QtCore.Signal()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.RightButton:
            self.rightClicked.emit()
            return
        super().mousePressEvent(event)


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
                interval = QtWidgets.QApplication.doubleClickInterval() + 40
                self._deselect_timer.start(interval)
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

    def _is_plain_click(self, event: QtGui.QMouseEvent) -> bool:
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

def _elide(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _compact_detection_status(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text.replace("감지된 언어:", "감지:")
    return " ".join(text.split())


def split_bulk_input(text: str) -> list[str]:
    """Split explicit separators while preserving phrases with spaces."""
    pieces = [piece.strip() for piece in BULK_INPUT_SPLIT_RE.split(text or "")]
    out: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if not piece:
            continue
        key = piece.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(piece)
    return out


class LoadingSpinner(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(15, 15)

    def set_running(self, running: bool) -> None:
        if running and not self._timer.isActive():
            self._timer.start()
        elif not running and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        base_pen = QtGui.QPen(QtGui.QColor(231, 225, 214, 62), 2)
        base_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(base_pen)
        painter.drawEllipse(rect)

        active_pen = QtGui.QPen(QtGui.QColor("#e8744f"), 2)
        active_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(active_pen)
        painter.drawArc(rect, (90 - self._angle) * 16, -110 * 16)
        painter.end()


class FlowLayout(QtWidgets.QLayout):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        margin: int = 0,
        spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QtWidgets.QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QtWidgets.QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QtWidgets.QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> QtCore.Qt.Orientations:
        return QtCore.Qt.Orientations(QtCore.Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QtCore.QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QtCore.QSize:
        return self.minimumSize()

    def minimumSize(self) -> QtCore.QSize:
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QtCore.QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _do_layout(self, rect: QtCore.QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()
