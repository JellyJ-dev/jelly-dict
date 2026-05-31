from __future__ import annotations

import logging

from PySide6 import QtCore

from app.core.errors import UnsupportedLanguageError
from app.services.lookup_service import LookupOutcome, LookupService

log = logging.getLogger(__name__)


class LookupWorker(QtCore.QObject):
    """Runs a single lookup on a worker thread."""

    finished = QtCore.Signal(object)  # LookupOutcome
    failed = QtCore.Signal(str)
    unsupported = QtCore.Signal(str)
    ambiguous = QtCore.Signal(str)

    def __init__(
        self,
        service: LookupService,
        word: str,
        forced_language: str | None,
        *,
        force_refresh: bool = False,
    ) -> None:
        super().__init__()
        self._service = service
        self._word = word
        self._forced = forced_language or None
        self._force_refresh = force_refresh

    @QtCore.Slot()
    def run(self) -> None:
        try:
            outcome: LookupOutcome = self._service.lookup(
                self._word,
                self._forced,
                force_refresh=self._force_refresh,
            )
        except UnsupportedLanguageError:
            self.unsupported.emit(self._word)
            return
        except Exception as exc:  # pragma: no cover - safety net
            log.exception("lookup worker crashed")
            self.failed.emit(str(exc))
            return
        if outcome.asked_user_for_language:
            self.ambiguous.emit(self._word)
            return
        self.finished.emit(outcome)
