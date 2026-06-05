from __future__ import annotations

import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest
import tomllib


JELLY_ROOT = Path(__file__).resolve().parents[1]
APP_FILES_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _copy_run_script(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    app_dir = repo / "jelly_dict"
    venv = app_dir / ".venv"
    scripts.mkdir(parents=True)
    (venv / "bin").mkdir(parents=True)

    run_script = scripts / "run.sh"
    shutil.copy2(APP_FILES_ROOT / "scripts" / "run.sh", run_script)
    shutil.copytree(APP_FILES_ROOT / "scripts" / "lib", scripts / "lib")
    run_script.chmod(0o755)

    (app_dir / ".quickstart_ok").write_text(
        f"quickstart_ok=1\napp_dir={app_dir.resolve()}\n",
        encoding="utf-8",
    )
    return run_script, app_dir, venv


def _write_fake_python(path: Path, *, version: str, supported: bool, prefix: Path) -> None:
    support_exit = "0" if supported else "1"
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case "${{1:-}}" in
  -V|--version)
    echo "Python {version}"
    exit 0
    ;;
  -c)
    echo "{prefix.resolve()}"
    exit 0
    ;;
  -)
    cat >/dev/null
    exit {support_exit}
    ;;
  -m)
    echo "unexpected app launch" >&2
    exit 42
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_release_version_is_consistent_across_public_entrypoints():
    pyproject = tomllib.loads((JELLY_ROOT / "pyproject.toml").read_text())
    version = pyproject["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version)

    installer = _read(PROJECT_ROOT / "Install jelly dict.command")
    install_script = _read(APP_FILES_ROOT / "scripts" / "install_app.sh")
    updater = _read(PROJECT_ROOT / "Update jelly dict.command")
    readme = _read(PROJECT_ROOT / "README.md")
    plist = plistlib.loads(
        (APP_FILES_ROOT / "packaging" / "macos" / "Info.plist").read_bytes()
    )

    assert 'app_files/scripts/install_app.sh' in installer
    assert f'JELLY_DICT_VERSION="{version}"' in install_script
    assert "JELLY_DICT_COMMAND_ROLE=update" in updater
    assert f"v{version}" in readme
    assert plist["CFBundleShortVersionString"] == version
    assert plist["CFBundleVersion"] == version


def test_python_runtime_policy_rejects_known_bad_qt_app_versions():
    pyproject = tomllib.loads((JELLY_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["requires-python"] == ">=3.11,<3.13"

    quickstart = _read(APP_FILES_ROOT / "scripts" / "quickstart.sh")
    run_script = _read(APP_FILES_ROOT / "scripts" / "run.sh")
    common_script = _read(APP_FILES_ROOT / "scripts" / "lib" / "common.sh")
    readme = _read(PROJECT_ROOT / "README.md")

    support_guard = "(3, 11) <= version < (3, 13)"
    assert support_guard in common_script
    assert "jelly_python_is_supported" in quickstart
    assert "jelly_python_is_supported" in run_script
    assert "Python 3.13 + Qt can abort" in quickstart
    assert "Python 3.13 + Qt" in readme
    assert "brew install python@3.12" in readme
    assert "python@3.13       # 권장" not in readme

    first_312 = common_script.index("python3.12")
    first_311 = common_script.index("python3.11")
    first_313 = common_script.index("python3.13")
    assert first_312 < first_313
    assert first_311 < first_313


def test_quickstart_qt_check_does_not_create_gui_application():
    quickstart = _read(APP_FILES_ROOT / "scripts" / "quickstart.sh")
    qt_check = quickstart.split("check_qt_runtime() {", 1)[1].split("\n}", 1)[0]

    assert "libqcocoa.dylib" in qt_check
    assert "QtWidgets" not in qt_check
    assert "QApplication" not in qt_check


def test_playwright_lookup_runtime_uses_chromium_not_webkit():
    quickstart = _read(APP_FILES_ROOT / "scripts" / "quickstart.sh")
    client = _read(JELLY_ROOT / "app" / "dictionary" / "playwright_client.py")
    readme = _read(PROJECT_ROOT / "README.md")

    assert "check_playwright_chromium()" in quickstart
    assert "p.chromium.executable_path" in quickstart
    assert "playwright install chromium" in quickstart
    assert "Playwright Chromium" in readme
    assert "playwright.chromium.launch" in client
    assert "playwright.webkit.launch" not in client
    assert "playwright install webkit" not in quickstart


def test_kokoro_spacy_model_install_uses_direct_wheel_url():
    quickstart = _read(APP_FILES_ROOT / "scripts" / "quickstart.sh")
    worker = _read(JELLY_ROOT / "app" / "ui" / "tts_install_worker.py")

    assert 'SPACY_EN_MODEL_VERSION="3.8.0"' in quickstart
    assert "github.com/explosion/spacy-models/releases/download" in quickstart
    assert "en_core_web_sm-${SPACY_EN_MODEL_VERSION}" in quickstart
    assert 'SPACY_EN_MODEL_VERSION = "3.8.0"' in worker
    assert "github.com/explosion/spacy-models/releases/download" in worker
    assert "en_core_web_sm-{SPACY_EN_MODEL_VERSION}" in worker
    assert "spacy download en_core_web_sm" not in quickstart
    assert '"spacy", "download"' not in worker


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("Install jelly dict.command"),
        Path("Update jelly dict.command"),
        Path("app_files/scripts/install_app.sh"),
        Path("app_files/scripts/quickstart.sh"),
        Path("app_files/scripts/run.sh"),
        Path("app_files/packaging/macos/build_app.sh"),
        Path("app_files/packaging/macos/launcher.sh"),
        Path("app_files/packaging/macos/make_icns.sh"),
    ],
)
def test_shell_entrypoints_parse(relative_path: Path):
    result = subprocess.run(
        ["/bin/bash", "-n", str(PROJECT_ROOT / relative_path)],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_macos_bundle_metadata_and_assets_are_present():
    plist = plistlib.loads(
        (APP_FILES_ROOT / "packaging" / "macos" / "Info.plist").read_bytes()
    )
    from app.core import config

    assert config.APP_DISPLAY_NAME == "Jelly Dict"
    assert plist["CFBundleDisplayName"] == "Jelly Dict"
    assert plist["CFBundleName"] == "Jelly Dict"
    assert plist["CFBundleExecutable"] == "jelly-dict"
    assert plist["CFBundleIconFile"] == "app_icon"
    assert plist["CFBundleIdentifier"] == "app.jelly-dict.local"
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["NSHighResolutionCapable"] is True

    assert (APP_FILES_ROOT / "assets" / "app-icon-1024.png").is_file()
    assert (APP_FILES_ROOT / "assets" / "app-icon.icns").is_file()
    assert (APP_FILES_ROOT / "packaging" / "macos" / "launcher.sh").is_file()


def test_updater_uses_installer_ui_entrypoint():
    installer = _read(PROJECT_ROOT / "Install jelly dict.command")
    install_script = _read(APP_FILES_ROOT / "scripts" / "install_app.sh")
    updater = _read(PROJECT_ROOT / "Update jelly dict.command")
    quickstart = _read(APP_FILES_ROOT / "scripts" / "quickstart.sh")
    package_script = _read(APP_FILES_ROOT / "scripts" / "make_user_package.sh")

    assert 'exec "${INSTALL_SCRIPT}" "$@"' in installer
    assert 'COMMAND_LABEL="Updater"' in install_script
    assert 'draw_border top "jelly dict  ·  ${COMMAND_LABEL}  ·  v${JELLY_DICT_VERSION}"' in install_script
    assert 'exec "${SCRIPT_DIR}/Install jelly dict.command" "$@"' in updater
    assert "${PUBLIC_ROOT}/Update jelly dict.command" in quickstart
    assert "${PUBLIC_ROOT}/app_files/LICENSE_NOTICE.txt" in quickstart
    assert '"${OUT_DIR}/Update jelly dict.command"' in package_script
    assert "LICENSE_NOTICE.txt" in package_script


def test_macos_app_launcher_embeds_python_instead_of_execing_python():
    build_script = _read(APP_FILES_ROOT / "packaging" / "macos" / "build_app.sh")

    assert "Py_InitializeFromConfig" in build_script
    assert "PyImport_ImportModule(\"app.main\")" in build_script
    assert 'setenv("JELLY_DICT_PYTHON", venv_python, 1);' in build_script
    assert "launcher: native embedded Python" in build_script
    assert "execv(\"/bin/bash\"" not in build_script
    assert "exec python -m app.main" not in build_script
    assert 'cp "${LAUNCHER}" "${MACOS_DIR}/jelly-dict"' not in build_script


def test_macos_process_name_helper_sets_nsprocessinfo(monkeypatch):
    calls: list[str] = []

    class FakeProcessInfo:
        def setProcessName_(self, name: str) -> None:
            calls.append(name)

    class FakeNSProcessInfo:
        @staticmethod
        def processInfo() -> FakeProcessInfo:
            return FakeProcessInfo()

    fake_foundation = types.ModuleType("Foundation")
    fake_foundation.NSProcessInfo = FakeNSProcessInfo
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)

    from app import main as app_main

    app_main._set_macos_process_name("Jelly Dict")

    assert calls == ["Jelly Dict"]


def test_qt_application_metadata_uses_jelly_dict_display_name():
    from PySide6 import QtCore, QtGui

    from app import main as app_main

    app_main._prepare_qt_application_metadata(QtCore, QtGui)

    assert QtCore.QCoreApplication.applicationName() == "Jelly Dict"
    assert QtGui.QGuiApplication.applicationDisplayName() == "Jelly Dict"


def test_macos_application_menu_title_is_refreshed(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeSubmenu:
        def setTitle_(self, title: str) -> None:
            calls.append(("submenu", title))

    class FakeMenuItem:
        def __init__(self) -> None:
            self._submenu = FakeSubmenu()

        def setTitle_(self, title: str) -> None:
            calls.append(("item", title))

        def submenu(self) -> FakeSubmenu:
            return self._submenu

    class FakeMainMenu:
        def __init__(self) -> None:
            self._item = FakeMenuItem()

        def itemAtIndex_(self, index: int) -> FakeMenuItem | None:
            assert index == 0
            return self._item

    class FakeNSApp:
        @staticmethod
        def mainMenu() -> FakeMainMenu:
            return FakeMainMenu()

    fake_appkit = types.ModuleType("AppKit")
    fake_appkit.NSApp = FakeNSApp
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setattr(sys, "platform", "darwin")

    from app import main as app_main

    app_main._refresh_macos_application_menu("Jelly Dict")

    assert calls == [("item", "Jelly Dict"), ("submenu", "Jelly Dict")]


def test_qt_plugin_paths_are_prepared_from_installed_pyside(monkeypatch, tmp_path: Path):
    pyside = tmp_path / "PySide6"
    platforms = pyside / "Qt" / "plugins" / "platforms"
    qml = pyside / "Qt" / "qml"
    platforms.mkdir(parents=True)
    qml.mkdir(parents=True)
    (pyside / "__init__.py").write_text("", encoding="utf-8")

    fake_module = types.ModuleType("PySide6")
    fake_module.__file__ = str(pyside / "__init__.py")
    monkeypatch.setitem(sys.modules, "PySide6", fake_module)
    monkeypatch.delenv("QT_PLUGIN_PATH", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM_PLUGIN_PATH", raising=False)
    monkeypatch.setenv("QML2_IMPORT_PATH", "/existing/qml")

    from app import main as app_main

    app_main._prepare_qt_plugin_paths()

    assert os.environ["QT_PLUGIN_PATH"] == str(pyside / "Qt" / "plugins")
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == str(platforms)
    assert os.environ["QML2_IMPORT_PATH"].split(os.pathsep) == [
        str(qml),
        "/existing/qml",
    ]


def test_run_script_rejects_python_313_virtualenv_before_launch(tmp_path: Path):
    run_script, _app_dir, venv = _copy_run_script(tmp_path)
    _write_fake_python(
        venv / "bin" / "python",
        version="3.13.13",
        supported=False,
        prefix=venv,
    )

    result = subprocess.run(
        ["/bin/bash", str(run_script)],
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Virtual environment Python is not supported" in result.stderr
    assert "Python 3.13.13" in result.stderr
    assert "unexpected app launch" not in result.stderr


def test_run_script_local_mode_requires_supported_python(tmp_path: Path):
    run_script, app_dir, _venv = _copy_run_script(tmp_path)
    (app_dir / ".install_mode").write_text("local\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_python(
        fake_bin / "python3",
        version="3.13.13",
        supported=False,
        prefix=tmp_path,
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    result = subprocess.run(
        ["/bin/bash", str(run_script)],
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )

    assert result.returncode == 1
    assert "Python 3.12 or 3.11 not found" in result.stderr
    assert "unexpected app launch" not in result.stderr
