from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class StartupPerf:
    enabled: bool = True
    _started: float = field(default_factory=time.perf_counter)

    @contextmanager
    def span(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.mark(name, start=start)

    def mark(self, name: str, *, start: float | None = None) -> None:
        if not self.enabled:
            return
        base = self._started if start is None else start
        elapsed_ms = int((time.perf_counter() - base) * 1000)
        log.info("startup %s=%sms", name, elapsed_ms)
