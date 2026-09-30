from __future__ import annotations

import logging

from PySide6 import QtCore

from app.core.duplicate_checker import DuplicateDecision
from app.core.models import VocabularyEntry
from app.services.save_service import PreparedSave, SaveService

log = logging.getLogger(__name__)


class SavePrepareWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, service: SaveService, entry: VocabularyEntry) -> None:
        super().__init__()
        self._service = service
        self._entry = entry

    @QtCore.Slot()
    def run(self) -> None:
        try:
            prepared = self._service.prepare(self._entry)
        except Exception as exc:
            log.exception("save prepare failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(prepared)


class SaveCommitWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        service: SaveService,
        prepared: PreparedSave,
        decision: DuplicateDecision | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._prepared = prepared
        self._decision = decision

    @QtCore.Slot()
    def run(self) -> None:
        try:
            outcome = self._service.commit(self._prepared, self._decision)
        except Exception as exc:
            log.exception("save commit failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(outcome)
