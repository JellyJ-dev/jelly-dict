from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

from app.storage.settings_store import Settings
from app.core.models import VocabularyEntry
from app.ui.main_window import (
    TransientStatusBar,
    _append_tts_pre_generation_job,
    runtime_status_summary,
)


MAIN_WINDOW = Path(__file__).resolve().parents[1] / "app" / "ui" / "main_window.py"


def test_runtime_status_summary_balances_language_paths():
    summary = runtime_status_summary(
        Settings(
            excel_path_en="/tmp/vocab_en.xlsx",
            excel_path_ja="/tmp/vocab_ja_really_long_name.xlsx",
            provider="naver_crawler",
            cache_enabled=True,
        )
    )

    assert summary.startswith("EN: vocab_en.xlsx · JA: vocab_ja_really_long_name.xlsx")
    assert "Excel:" not in summary
    assert " / " not in summary
    assert summary.endswith("· Naver · cache on")


def test_main_window_hides_native_macos_titlebar_chrome():
    source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert 'self.setWindowTitle("")' in source
    assert "setTitleVisibility_" in source
    assert "NSWindowTitleHidden" in source
    assert "ExpandedClientAreaHint" in source
    assert "NoTitleBarBackgroundHint" in source
    assert "setTitlebarAppearsTransparent_(True)" in source
    assert "setTitlebarSeparatorStyle_(NSTitlebarSeparatorStyleNone)" in source
    assert "NSWindowStyleMaskFullSizeContentView" in source
    assert "setAutorecalculatesContentBorderThickness_forEdge_" in source
    assert "setContentBorderThickness_forEdge_(0, NSMaxYEdge)" in source
    assert "PlatformSurface" in source
    assert "MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT = 52" in source
    assert "performZoom_" in source
    assert "MouseButtonDblClick" in source
    assert "globalPosition()" in source
    assert "_titlebar_drag_origin" in source
    assert "MouseMove" in source
    assert "startSystemMove()" in source
    assert "frameGeometry().topLeft()" in source
    assert "_titlebar_zoom_restore_geometry" in source
    assert "_restore_titlebar_zoom_geometry()" in source
    assert "QtCore.QRect(self.geometry())" in source
    assert "setGeometry(restore_geometry)" in source
    assert "removeEventFilter(self)" in source
    assert "NSToolbar" not in source
    assert "setUnifiedTitleAndToolBarOnMac" not in source


def test_recent_clear_uses_undo_toast_contract():
    source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "snapshot_recent_lookups()" in source
    assert "restore_recent_lookups(snapshot)" in source
    assert 'f"{removed}개를 삭제했습니다."' in source
    assert "self._restore_recent(snapshot, removed)" in source


def test_main_window_close_shortcut_hides_app_and_can_restore():
    source = MAIN_WINDOW.read_text(encoding="utf-8")

    assert "QKeySequence.StandardKey.Close" in source
    assert "self.close_shortcut.activated.connect(self._hide_main_window)" in source
    assert "NSApp.hide_(None)" in source
    assert "_restore_hidden_main_window" in source
    assert "ApplicationActivate" in source
    assert "applicationStateChanged.connect(self._on_application_state_changed)" in source
    assert "self.close_shortcut.activated.connect(self.hide)" not in source
    assert "self.close_shortcut.activated.connect(self.showMinimized)" not in source
    assert "self.close_shortcut.activated.connect(self.close)" not in source


def test_transient_status_bar_auto_hides_messages(qtbot):
    parent = QtWidgets.QWidget()
    parent.resize(640, 480)
    qtbot.addWidget(parent)
    status = TransientStatusBar(parent)

    assert status.isHidden()
    assert status.DEFAULT_TIMEOUT_MS == 4000
    assert status.FADE_DURATION_MS == 240

    status.showMessage("1개 삭제를 되돌렸습니다.", 20)

    assert status.currentMessage() == "1개 삭제를 되돌렸습니다."
    assert not status.isHidden()
    assert status._dismiss_timer.interval() == 20

    qtbot.waitUntil(status.isHidden, timeout=1000)
    assert status.currentMessage() == ""
    assert status._opacity.opacity() == 0.0

    status.showMessage("")
    assert status.isHidden()


def test_transient_status_bar_is_overlay_and_does_not_resize_parent(qtbot):
    parent = QtWidgets.QWidget()
    parent.resize(640, 480)
    qtbot.addWidget(parent)
    status = TransientStatusBar(parent)

    before = parent.size()
    status.showMessage("모든 조회가 완료되었습니다.", 20)

    assert parent.size() == before
    assert status.parentWidget() is parent
    assert status.y() >= parent.height() - status.height() - 12


def test_tts_pre_generation_queue_keeps_latest_and_stays_bounded():
    settings = Settings()
    queue: list[tuple[Settings, VocabularyEntry]] = []

    for idx in range(5):
        _append_tts_pre_generation_job(
            queue,
            settings,
            VocabularyEntry(language="en", word=f"word-{idx}"),
            limit=3,
        )
    _append_tts_pre_generation_job(
        queue,
        settings,
        VocabularyEntry(language="en", word="word-3", meanings_summary="latest"),
        limit=3,
    )

    assert len(queue) == 3
    assert [entry.word for _, entry in queue] == ["word-2", "word-4", "word-3"]
    assert queue[-1][1].meanings_summary == "latest"
