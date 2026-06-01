from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets


class UndoToast(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("undoToast")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        self._undo_callback: Callable[[], None] | None = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 10, 9)
        layout.setSpacing(10)

        self.message_label = QtWidgets.QLabel("")
        self.message_label.setObjectName("undoToastMessage")
        self.message_label.setTextFormat(QtCore.Qt.PlainText)
        layout.addWidget(self.message_label, 1)

        self.undo_button = QtWidgets.QPushButton("되돌리기")
        self.undo_button.setObjectName("undoToastButton")
        self.undo_button.clicked.connect(self._undo)
        layout.addWidget(self.undo_button)

        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        self._dismiss_timer = QtCore.QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._fade_out)

        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade.finished.connect(self.hide)

        parent.installEventFilter(self)
        self.hide()

    def show_message(
        self,
        message: str,
        undo_callback: Callable[[], None] | None,
        *,
        duration_ms: int = 3000,
    ) -> None:
        self._fade.stop()
        self._dismiss_timer.stop()
        self._undo_callback = undo_callback
        self.message_label.setText(message)
        self.undo_button.setVisible(undo_callback is not None)
        self._opacity.setOpacity(1.0)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        if duration_ms > 0:
            self._dismiss_timer.start(duration_ms)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.parent() and event.type() == QtCore.QEvent.Resize:
            self._place()
        return super().eventFilter(watched, event)

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        hint = self.sizeHint()
        width = min(max(hint.width(), 260), 380)
        height = max(hint.height(), 46)
        self.resize(width, height)
        x = max(18, (parent.width() - width) // 2)
        y = max(18, parent.height() - height - 42)
        self.move(x, y)

    def _fade_out(self) -> None:
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _undo(self) -> None:
        callback = self._undo_callback
        self._undo_callback = None
        self._dismiss_timer.stop()
        self._fade.stop()
        self.hide()
        if callback is not None:
            callback()
