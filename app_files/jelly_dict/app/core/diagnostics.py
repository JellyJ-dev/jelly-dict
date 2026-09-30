from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from types import TracebackType
from typing import Callable, Literal, get_args

DiagnosticCategory = Literal[
    "lookup",
    "workbook_read",
    "workbook_write",
    "workbook_search",
    "export",
    "ocr",
    "tts",
    "recovery",
    "cache_migration",
]
DiagnosticResult = Literal[
    "success",
    "cache_hit",
    "empty",
    "not_found",
    "parse_failed",
    "network_error",
    "rate_limited",
    "unsupported",
    "failed",
    "cancelled",
    "skipped",
    "conflict",
]

DIAGNOSTIC_MARKER = "JELLY_DIAGNOSTIC "
DIAGNOSTIC_SCHEMA_VERSION = 1
_CATEGORIES = frozenset(get_args(DiagnosticCategory))
_RESULTS = frozenset(get_args(DiagnosticResult))
_logger = logging.getLogger("jelly_dict.structured")


@dataclass(frozen=True)
class DiagnosticEvent:
    schema_version: int
    event: str
    category: DiagnosticCategory
    duration_ms: float
    result_type: DiagnosticResult
    row_count: int | None = None

    def to_json(self) -> str:
        payload = {key: value for key, value in asdict(self).items() if value is not None}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class DiagnosticOperation:
    def __init__(
        self,
        category: DiagnosticCategory,
        *,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        _validate_category(category)
        self.category = category
        self._clock_ns = clock_ns
        self._started_ns = clock_ns()
        self._finished = False

    def finish(
        self,
        result_type: DiagnosticResult = "success",
        *,
        row_count: int | None = None,
    ) -> None:
        if self._finished:
            return
        _validate_result(result_type)
        if row_count is not None and (type(row_count) is not int or row_count < 0):
            raise ValueError("row_count must be a non-negative integer")
        elapsed_ns = max(0, self._clock_ns() - self._started_ns)
        event = DiagnosticEvent(
            schema_version=DIAGNOSTIC_SCHEMA_VERSION,
            event="operation",
            category=self.category,
            duration_ms=round(elapsed_ns / 1_000_000, 3),
            result_type=result_type,
            row_count=row_count,
        )
        _emit(event)
        self._finished = True

    def __enter__(self) -> DiagnosticOperation:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        self.finish("failed" if exc_type is not None else "success")
        return False


def diagnostic_operation(category: DiagnosticCategory) -> DiagnosticOperation:
    return DiagnosticOperation(category)


def record_operation(
    category: DiagnosticCategory,
    result_type: DiagnosticResult,
    *,
    duration_ms: float,
    row_count: int | None = None,
) -> None:
    _validate_category(category)
    _validate_result(result_type)
    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if row_count is not None and (type(row_count) is not int or row_count < 0):
        raise ValueError("row_count must be a non-negative integer")
    event = DiagnosticEvent(
        DIAGNOSTIC_SCHEMA_VERSION,
        "operation",
        category,
        round(float(duration_ms), 3),
        result_type,
        row_count,
    )
    _emit(event)


def _emit(event: DiagnosticEvent) -> None:
    try:
        _logger.info("%s%s", DIAGNOSTIC_MARKER, event.to_json())
    except Exception:
        # Diagnostics must never alter the user operation they observe.
        return


def _validate_category(category: str) -> None:
    if category not in _CATEGORIES:
        raise ValueError("unsupported diagnostic category")


def _validate_result(result_type: str) -> None:
    if result_type not in _RESULTS:
        raise ValueError("unsupported diagnostic result type")
