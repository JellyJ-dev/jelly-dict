from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class TransientStatusBar(QtWidgets.QFrame):
    DEFAULT_TIMEOUT_MS = 4000
    FADE_DURATION_MS = 240

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transientStatusBar")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._message = ""
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(0)
        self.message_label = QtWidgets.QLabel("")
        self.message_label.setObjectName("transientStatusMessage")
        self.message_label.setTextFormat(QtCore.Qt.PlainText)
        self.message_label.setMinimumWidth(0)
        self.message_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        layout.addWidget(self.message_label)
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._dismiss_timer = QtCore.QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._fade_out)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(self.FADE_DURATION_MS)
        self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade.finished.connect(self._finish_fade_out)
        if parent is not None:
            parent.installEventFilter(self)
        self.hide()

    def showMessage(self, message: str, timeout: int = 0) -> None:  # noqa: N802
        message = (message or "").strip()
        if not message:
            self.clearMessage()
            return
        self._dismiss_timer.stop()
        self._fade.stop()
        self._message = message
        self.message_label.setText(message)
        self.message_label.setToolTip(message)
        self.adjustSize()
        self._place()
        self._opacity.setOpacity(1.0)
        self.show()
        self.raise_()
        self._dismiss_timer.start(timeout if timeout > 0 else self.DEFAULT_TIMEOUT_MS)

    def clearMessage(self) -> None:  # noqa: N802
        self._dismiss_timer.stop()
        self._fade.stop()
        self._message = ""
        self.message_label.setText("")
        self.message_label.setToolTip("")
        self._opacity.setOpacity(0.0)
        self.hide()

    def currentMessage(self) -> str:  # noqa: N802
        return self._message

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.parent() and event.type() == QtCore.QEvent.Resize:
            self._place()
        return super().eventFilter(watched, event)

    def _fade_out(self) -> None:
        if self.isHidden() or not self._message:
            return
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.setDuration(self.FADE_DURATION_MS)
        self._fade.start()

    def _finish_fade_out(self) -> None:
        if self._opacity.opacity() > 0.01:
            return
        self._message = ""
        self.message_label.setText("")
        self.message_label.setToolTip("")
        self._opacity.setOpacity(0.0)
        self.hide()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        hint = self.sizeHint()
        text_width = self.message_label.fontMetrics().horizontalAdvance(self._message)
        width = min(max(hint.width(), text_width + 20, 220), max(220, parent.width() - 24))
        height = max(hint.height(), 28)
        self.resize(width, height)
        self._sync_message_elide()
        self.move(8, max(8, parent.height() - height - 8))

    def _sync_message_elide(self) -> None:
        available = max(40, self.width() - 20)
        self.message_label.setText(
            self.message_label.fontMetrics().elidedText(
                self._message,
                QtCore.Qt.ElideRight,
                available,
            )
        )
