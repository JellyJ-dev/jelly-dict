from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtCore

from app.core.models import normalize_word_key
from app.storage import excel_writer
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)


class SavedWordsWorker(QtCore.QObject):
    finished = QtCore.Signal(object)  # set[tuple[str, str]]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @QtCore.Slot()
    def run(self) -> None:
        saved: set[tuple[str, str]] = set()
        for lang in ("en", "ja"):
            path = Path(self._settings.excel_path_for(lang))
            if not path.exists():
                continue
            try:
                for entry in excel_writer.list_entries(path):
                    if entry.language == lang and (entry.word or "").strip():
                        saved.add((lang, normalize_word_key(entry.word, lang)))
            except Exception as exc:
                log.warning("saved words cache load failed from %s: %s", path, exc)
        self.finished.emit(saved)
