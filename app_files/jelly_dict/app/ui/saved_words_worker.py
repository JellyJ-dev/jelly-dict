from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtCore

from app.core.models import normalize_word_key
from app.storage.excel_repository import WorkbookRepository
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)


class SavedWordsWorker(QtCore.QObject):
    finished = QtCore.Signal(object)  # set[tuple[str, str]]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @QtCore.Slot()
    def run(self) -> None:
        self.finished.emit(load_saved_words(self._settings))


def load_saved_words(
    settings: Settings,
    repository: WorkbookRepository | None = None,
) -> set[tuple[str, str]]:
    """Read saved word keys without requiring a Qt worker object."""
    repository = repository or WorkbookRepository()
    saved: set[tuple[str, str]] = set()
    for lang in ("en", "ja"):
        path = Path(settings.excel_path_for(lang))
        if not path.exists():
            continue
        try:
            snapshot = repository.read_snapshot(path)
            for row in snapshot.rows:
                raw_language = next(
                    (str(cell.value or "").strip() for cell in row.cells if cell.key == "language"),
                    "",
                )
                entry = row.entry
                if raw_language == lang and (entry.word or "").strip():
                    saved.add((lang, normalize_word_key(entry.word, lang)))
        except Exception as exc:
            log.warning("saved words cache load failed from %s: %s", path, exc)
    return saved
