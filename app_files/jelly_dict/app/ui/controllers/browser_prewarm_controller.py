from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from app.dictionary.base import DictionaryProvider
from app.dictionary.naver_crawler import NaverDictionaryCrawlerProvider
from app.ui.startup_perf import StartupPerf

log = logging.getLogger(__name__)


class BrowserPrewarmController(QtCore.QObject):
    def __init__(
        self,
        parent: QtCore.QObject,
        provider_getter: Callable[[], DictionaryProvider],
        startup_perf: StartupPerf,
    ) -> None:
        super().__init__(parent)
        self._provider_getter = provider_getter
        self._startup_perf = startup_perf
        self._started = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._prewarm)

    def schedule(self) -> None:
        if self._started:
            return
        self._timer.start()

    def _prewarm(self) -> None:
        """Warm Playwright only after real user input.

        Lookup still starts Playwright lazily when needed; this path is only
        an interactive latency optimization.
        """
        if self._started:
            return
        platform = QtWidgets.QApplication.platformName().lower()
        if platform in {"offscreen", "minimal"}:
            return
        provider = self._provider_getter()
        if not isinstance(provider, NaverDictionaryCrawlerProvider):
            return
        self._started = True

        def warm() -> None:
            try:
                with self._startup_perf.span("playwright_prewarm"):
                    provider.client.start()
                log.info("playwright pre-warmed")
            except Exception as exc:
                log.warning("pre-warm failed: %s", exc)

        threading.Thread(target=warm, name="jelly-dict-prewarm", daemon=True).start()
