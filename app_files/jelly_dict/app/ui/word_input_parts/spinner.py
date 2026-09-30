from PySide6 import QtCore, QtGui, QtWidgets


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
