from PySide6 import QtCore, QtGui, QtWidgets


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
