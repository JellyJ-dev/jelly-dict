from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from app.core import config
from app.platform.macos import application_display_name as _application_display_name
from app.platform.macos import prepare_macos_gui_process as _prepare_macos_gui_process
from app.platform.macos import refresh_macos_application_menu as _refresh_macos_application_menu
from app.platform.macos import set_macos_process_name as _set_macos_process_name


def _quickstart_completed() -> bool:
    path = config.quickstart_state_path()
    if not path.exists():
        return False
    try:
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return False
    return (
        values.get("quickstart_ok") == "1"
        and values.get("app_dir") == str(config.project_root())
    )


def _print_quickstart_required() -> None:
    print(
        "jelly dict 초기 설정이 완료되지 않았습니다.\n"
        "프로젝트 맨 위의 'Install jelly dict.command'를 먼저 실행하세요.\n"
        "수동 설치/직접 실행은 지원하지 않습니다.",
        file=sys.stderr,
    )


def _setup_logging() -> None:
    log_path: Path = config.log_path()
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)


def _prepare_qt_application_metadata(QtCore, QtGui, app=None) -> None:
    display_name = _application_display_name()
    QtCore.QCoreApplication.setApplicationName(display_name)
    QtCore.QCoreApplication.setOrganizationName(display_name)
    QtGui.QGuiApplication.setApplicationDisplayName(display_name)
    if app is not None:
        app.setApplicationName(display_name)
        app.setApplicationDisplayName(display_name)


def _prepare_qt_plugin_paths() -> None:
    try:
        import PySide6
    except Exception:
        return

    pyside_root = Path(PySide6.__file__).resolve().parent
    plugins = pyside_root / "Qt" / "plugins"
    platforms = plugins / "platforms"
    qml = pyside_root / "Qt" / "qml"

    if platforms.exists():
        os.environ["QT_PLUGIN_PATH"] = str(plugins)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms)

    if qml.exists():
        existing = os.environ.get("QML2_IMPORT_PATH", "")
        parts = [part for part in existing.split(os.pathsep) if part]
        qml_text = str(qml)
        if qml_text not in parts:
            os.environ["QML2_IMPORT_PATH"] = os.pathsep.join([qml_text, *parts])


def main() -> int:
    if not _quickstart_completed():
        _print_quickstart_required()
        return 2

    _setup_logging()
    _prepare_macos_gui_process()
    _prepare_qt_plugin_paths()

    # Touch runtime dir / settings / Excel target so the app is ready.
    config.runtime_dir()
    from app.storage.settings_store import SettingsStore

    settings = SettingsStore().load()
    excel_dir = Path(settings.default_excel_dir)
    excel_dir.mkdir(parents=True, exist_ok=True)

    # Defer Qt import so unit tests / CLI use don't need a display.
    from PySide6 import QtCore, QtGui, QtWidgets

    from app.ui.main_window import MainWindow

    # QtMultimedia plays our TTS mp3s via ffmpeg under the hood and
    # emits cosmetic "[mp3float] Could not update timestamps for skipped
    # samples" warnings on every playback. They're harmless decoder
    # noise — silence them so the console stays focused on real issues.
    def _qt_msg_filter(_mode, _ctx, message):
        if "mp3float" in message and "timestamps" in message:
            return
        sys.stderr.write(message + "\n")

    QtCore.qInstallMessageHandler(_qt_msg_filter)

    _prepare_qt_application_metadata(QtCore, QtGui)
    app = QtWidgets.QApplication(sys.argv)
    _prepare_qt_application_metadata(QtCore, QtGui, app)
    _refresh_macos_application_menu()
    window = MainWindow()
    _refresh_macos_application_menu()
    window.show()
    _refresh_macos_application_menu()
    QtCore.QTimer.singleShot(0, _refresh_macos_application_menu)
    QtCore.QTimer.singleShot(250, _refresh_macos_application_menu)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
