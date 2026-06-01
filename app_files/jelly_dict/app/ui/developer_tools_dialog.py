from __future__ import annotations

import platform
import sys
from importlib import metadata
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.core import config
from app.storage.settings_store import Settings, SettingsStore
from app.ui.dialog_shortcuts import install_standard_close_shortcut


class DeveloperToolsDialog(QtWidgets.QDialog):
    """Small log viewer kept out of the primary user workflow."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("개발자 도구")
        self.resize(820, 560)
        self._log_path = config.log_path()
        install_standard_close_shortcut(self)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QtWidgets.QHBoxLayout()
        layout.addLayout(header)
        title = QtWidgets.QLabel("앱 로그")
        title.setObjectName("dialogTitle")
        header.addWidget(title)
        header.addStretch(1)
        path_label = QtWidgets.QLabel(str(self._log_path))
        path_label.setObjectName("mutedLabel")
        path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        header.addWidget(path_label)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        font.setPointSize(12)
        self.log_view.setFont(font)
        layout.addWidget(self.log_view, 1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("mutedLabel")
        layout.addWidget(self.status_label)

        buttons = QtWidgets.QHBoxLayout()
        layout.addLayout(buttons)
        self.refresh_btn = QtWidgets.QPushButton("새로고침")
        self.copy_btn = QtWidgets.QPushButton("로그 복사")
        self.diagnostics_btn = QtWidgets.QPushButton("진단 정보 복사")
        self.open_location_btn = QtWidgets.QPushButton("로그 파일 위치 열기")
        self.clear_btn = QtWidgets.QPushButton("로그 비우기")
        close_btn = QtWidgets.QPushButton("닫기")
        buttons.addWidget(self.refresh_btn)
        buttons.addWidget(self.copy_btn)
        buttons.addWidget(self.diagnostics_btn)
        buttons.addWidget(self.open_location_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        self.refresh_btn.clicked.connect(self.refresh)
        self.copy_btn.clicked.connect(self._copy)
        self.diagnostics_btn.clicked.connect(self._copy_diagnostics)
        self.open_location_btn.clicked.connect(self._open_location)
        self.clear_btn.clicked.connect(self._clear)
        close_btn.clicked.connect(self.accept)

    @QtCore.Slot()
    def refresh(self) -> None:
        if not self._log_path.exists():
            self.log_view.setPlainText("로그 파일이 아직 없습니다.")
            return
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.log_view.setPlainText(f"로그를 읽을 수 없습니다: {exc}")
            return
        self.log_view.setPlainText(text or "로그가 비어 있습니다.")
        cursor = self.log_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.log_view.setTextCursor(cursor)

    def _copy(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.log_view.toPlainText())
        self.status_label.setText("로그가 클립보드에 복사되었습니다.")

    def _copy_diagnostics(self) -> None:
        QtWidgets.QApplication.clipboard().setText(build_diagnostics_text(self._log_path))
        self.status_label.setText("진단 정보가 클립보드에 복사되었습니다.")

    def _open_location(self) -> None:
        path = self._log_path.parent if self._log_path.parent.exists() else config.runtime_dir()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _clear(self) -> None:
        try:
            Path(self._log_path).write_text("", encoding="utf-8")
        except OSError as exc:
            self.log_view.setPlainText(f"로그를 비울 수 없습니다: {exc}")
            return
        self.refresh()
        self.status_label.setText("로그를 비웠습니다.")


def build_diagnostics_text(log_path: Path | None = None, log_tail_lines: int = 80) -> str:
    settings = SettingsStore().load()
    log_path = log_path or config.log_path()
    lines = [
        f"{config.APP_DISPLAY_NAME} diagnostics",
        "",
        "[runtime]",
        f"app_version: {_app_version()}",
        f"python: {sys.version.split()[0]}",
        f"platform: {platform.platform()}",
        f"qt: {QtCore.qVersion()}",
        f"pyside: {_pyside_version()}",
        f"app_dir: {config.project_root()}",
        f"runtime_dir: {config.runtime_dir()}",
        f"settings_path: {config.settings_path()}",
        f"cache_db_path: {config.cache_db_path()}",
        f"log_path: {log_path}",
        "",
        "[settings]",
        *_settings_summary(settings),
        "",
        f"[log tail: last {log_tail_lines} lines]",
        _log_tail(log_path, log_tail_lines),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _settings_summary(settings: Settings) -> list[str]:
    return [
        f"provider: {settings.provider}",
        f"ocr_provider: {settings.ocr_provider}",
        f"cache_enabled: {settings.cache_enabled}",
        f"show_preview: {settings.show_preview}",
        f"duplicate_policy: {settings.duplicate_policy}",
        f"request_delay_seconds: {settings.request_delay_seconds}",
        f"excel_path_en: {settings.excel_path_for('en')}",
        f"excel_path_ja: {settings.excel_path_for('ja')}",
        f"anki_path_en: {settings.anki_path_for('en')}",
        f"anki_path_ja: {settings.anki_path_for('ja')}",
        f"ankiconnect_enabled: {settings.ankiconnect_enabled}",
        f"tts_enabled: {settings.tts_enabled}",
        f"tts_engine_en: {settings.tts_engine_en}",
        f"tts_engine_ja: {settings.tts_engine_ja}",
        f"anki_export_confirm_mode: {settings.anki_export_confirm_mode}",
    ]


def _log_tail(path: Path, line_count: int) -> str:
    if not path.exists():
        return "로그 파일이 아직 없습니다."
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"로그를 읽을 수 없습니다: {exc}"
    if not lines:
        return "로그가 비어 있습니다."
    return "\n".join(lines[-line_count:])


def _app_version() -> str:
    try:
        return metadata.version("jelly-dict")
    except metadata.PackageNotFoundError:
        return "editable/uninstalled"


def _pyside_version() -> str:
    try:
        import PySide6

        return PySide6.__version__
    except Exception:
        return "unknown"
