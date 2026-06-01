from __future__ import annotations

from PySide6 import QtWidgets

from app.storage.settings_store import Settings
from app.ui.main_window import TransientStatusBar, runtime_status_summary


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
