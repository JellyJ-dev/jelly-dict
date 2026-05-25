from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets


class _ExportPopup(QtWidgets.QFrame):
    exportRequested = QtCore.Signal(str, bool)  # audio_policy, force_options
    settingsRequested = QtCore.Signal()
    closed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("ankiExportPopupWindow")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setFixedWidth(276)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.panel = QtWidgets.QFrame()
        self.panel.setObjectName("ankiExportPopup")
        self.panel.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        root.addWidget(self.panel)

        layout = QtWidgets.QVBoxLayout(self.panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.status = QtWidgets.QLabel("현재 설정")
        self.status.setObjectName("ankiExportPopupStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addWidget(self._row("옵션 확인 후 내보내기...", "settings", True))
        layout.addWidget(self._separator())
        layout.addWidget(self._row("이번만 TTS 포함", "force_tts", False))
        layout.addWidget(self._row("이번만 TTS 없이", "no_tts", False))
        layout.addWidget(self._row("Anki 카드 음성 비우기", "remove_audio", True))
        layout.addWidget(self._separator())

        settings = QtWidgets.QPushButton("Anki / TTS 설정")
        settings.setObjectName("ankiExportPopupItem")
        settings.clicked.connect(self._emit_settings)
        layout.addWidget(settings)

    def set_status_text(self, text: str) -> None:
        self.status.setText(text or "현재 설정 사용")

    def show_for(self, anchor: QtWidgets.QWidget) -> None:
        self.adjustSize()
        bottom_right = anchor.mapToGlobal(QtCore.QPoint(anchor.width(), anchor.height() + 6))
        self.move(bottom_right.x() - self.width(), bottom_right.y())
        self.show()
        self.raise_()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()

    def _row(
        self,
        text: str,
        policy: str,
        force_options: bool,
        variant: str = "normal",
    ) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setObjectName(
            "ankiExportPopupWarning" if variant == "warning" else "ankiExportPopupItem"
        )
        button.clicked.connect(
            lambda _checked=False, p=policy, f=force_options: self._emit_export(p, f)
        )
        return button

    def _separator(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setObjectName("ankiExportPopupSeparator")
        line.setFrameShape(QtWidgets.QFrame.HLine)
        return line

    def _emit_export(self, policy: str, force_options: bool) -> None:
        self.hide()
        self.exportRequested.emit(policy, force_options)

    def _emit_settings(self) -> None:
        self.hide()
        self.settingsRequested.emit()


class _AnkiMainButton(QtWidgets.QAbstractButton):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(134, 34)
        self.setText("Anki 내보내기")

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        active = self.isDown() or self.underMouse()
        color = QtGui.QColor("#e8744f") if active else QtGui.QColor("#d4cec4")
        if active:
            painter.setBrush(QtGui.QColor("#282826"))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 11, 11)

        font = QtGui.QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QtGui.QFont.Weight.Bold)
        painter.setFont(font)
        metrics = QtGui.QFontMetricsF(font)
        text = self.text()
        text_width = math.ceil(metrics.horizontalAdvance(text))
        icon_size = 17.0
        gap = 8.0
        total_width = icon_size + gap + text_width
        left = round((self.width() - total_width) / 2)
        center_y = round(self.height() / 2)

        _draw_star(
            painter,
            QtCore.QPointF(left + icon_size / 2, center_y),
            7.7,
            color,
        )
        text_bounds = metrics.tightBoundingRect(text)
        baseline = center_y - (text_bounds.top() + text_bounds.bottom()) / 2
        painter.setPen(color)
        painter.drawText(QtCore.QPointF(left + icon_size + gap, baseline), text)
        painter.end()


class _AnkiOptionButton(QtWidgets.QAbstractButton):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(38, 34)
        self.setToolTip("Anki 내보내기 옵션")

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        active = self.isDown() or self.underMouse()
        color = QtGui.QColor("#e8744f") if active else QtGui.QColor("#d4cec4")
        if active:
            painter.setBrush(QtGui.QColor("#282826"))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 11, 11)

        painter.setBrush(color)
        painter.setPen(QtCore.Qt.NoPen)
        diameter = 4.0
        gap = 5.0
        total_width = diameter * 3 + gap * 2
        left = round((self.width() - total_width) / 2)
        top = round((self.height() - diameter) / 2)
        for index in range(3):
            painter.drawEllipse(
                QtCore.QRectF(left + index * (diameter + gap), top, diameter, diameter)
            )
        painter.end()


class AnkiExportButton(QtWidgets.QWidget):
    exportRequested = QtCore.Signal(str, str, bool)  # language, audio_policy, force_options
    settingsRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._language = "en"
        self._status_text = ""
        self.setObjectName("ankiExportButton")
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.main_button = _AnkiMainButton(self)
        self.option_button = _AnkiOptionButton(self)
        self.main_button.clicked.connect(lambda: self._emit_export("settings", False))
        self.option_button.clicked.connect(self._show_popup)
        layout.addWidget(self.main_button)
        layout.addWidget(self.option_button)
        self.setFixedSize(174, 34)

        self._popup = _ExportPopup(self)
        self._popup.exportRequested.connect(
            lambda policy, force: self._emit_export(policy, force)
        )
        self._popup.settingsRequested.connect(self.settingsRequested.emit)
        self._popup.closed.connect(self._sync_hover_state)
        self.set_status_text("")

    def set_language(self, language: str) -> None:
        self._language = language if language in ("en", "ja") else "en"

    def set_status_text(self, text: str) -> None:
        self._status_text = text
        tooltip = "현재 단어장을 Anki APKG로 내보내기"
        if text:
            tooltip += f"\n{text}"
        self.setToolTip(tooltip)
        self.main_button.setToolTip(tooltip)
        self.option_button.setToolTip(f"Anki 내보내기 옵션\n{text}" if text else "Anki 내보내기 옵션")

    def _show_popup(self) -> None:
        self._popup.set_status_text(self._status_text)
        self._popup.show_for(self.option_button)

    def _emit_export(self, audio_policy: str, force_options: bool) -> None:
        self.exportRequested.emit(self._language, audio_policy, force_options)

    def _sync_hover_state(self) -> None:
        self.main_button.update()
        self.option_button.update()


def _draw_star(
    painter: QtGui.QPainter,
    center: QtCore.QPointF,
    radius: float,
    color: QtGui.QColor,
) -> None:
    path = QtGui.QPainterPath()
    inner = radius * 0.48
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        r = radius if index % 2 == 0 else inner
        point = QtCore.QPointF(center.x() + math.cos(angle) * r, center.y() + math.sin(angle) * r)
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    painter.setBrush(QtCore.Qt.NoBrush)
    pen = QtGui.QPen(color, 1.8)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(pen)
    painter.drawPath(path)
