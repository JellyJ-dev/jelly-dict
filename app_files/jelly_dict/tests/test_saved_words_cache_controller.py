from __future__ import annotations

from PySide6 import QtCore

from app.storage.settings_store import Settings
from app.ui.controllers.saved_words_cache_controller import SavedWordsCacheController


class _InputViewStub:
    _list_mode = "recent"


class _WordbookControllerStub:
    def __init__(self) -> None:
        self.saved_words: set[tuple[str, str]] | None = None

    def set_saved_words_cache(self, saved_words: set[tuple[str, str]]) -> None:
        self.saved_words = saved_words


class _StartupPerfStub:
    def __init__(self) -> None:
        self.marked: list[str] = []

    def mark(self, name: str, *, start: float | None = None) -> None:
        self.marked.append(name)


def test_saved_words_cache_controller_uses_non_qt_worker_thread(qtbot, monkeypatch):
    parent = QtCore.QObject()
    input_view = _InputViewStub()
    wordbook = _WordbookControllerStub()
    startup_perf = _StartupPerfStub()
    refresh_calls: list[bool] = []

    monkeypatch.setattr(
        "app.ui.controllers.saved_words_cache_controller.load_saved_words",
        lambda settings: {("en", "apple")},
    )

    controller = SavedWordsCacheController(
        parent,
        lambda: Settings(default_excel_dir=""),
        input_view,  # type: ignore[arg-type]
        wordbook,  # type: ignore[arg-type]
        lambda: refresh_calls.append(True),
        startup_perf,  # type: ignore[arg-type]
    )

    controller.start()

    qtbot.waitUntil(lambda: wordbook.saved_words == {("en", "apple")}, timeout=1000)
    assert refresh_calls == [True]
    assert startup_perf.marked == ["saved_words_cache"]
    assert controller.stop()
