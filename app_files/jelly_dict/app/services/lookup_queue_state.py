"""Pure lookup queue state with O(1) deduplication and explicit collections."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class LookupJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


@dataclass(slots=True)
class LookupJob:
    word: str
    forced_language: str
    force_refresh: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)
    status: LookupJobStatus = LookupJobStatus.PENDING

    @property
    def dedupe_key(self) -> tuple[str, str, bool]:
        return (
            self.word.strip().lower(),
            (self.forced_language or "").strip().lower(),
            self.force_refresh,
        )


class LookupQueueState:
    def __init__(self) -> None:
        self._pending: OrderedDict[str, LookupJob] = OrderedDict()
        self._failed: OrderedDict[str, LookupJob] = OrderedDict()
        self._dedupe: set[tuple[str, str, bool]] = set()
        self._active: LookupJob | None = None
        self._total = 0

    @property
    def active(self) -> LookupJob | None:
        return self._active

    @property
    def total(self) -> int:
        return self._total

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def failed_count(self) -> int:
        return len(self._failed)

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    def contains(
        self,
        word: str,
        forced_language: str,
        force_refresh: bool = False,
    ) -> bool:
        return self._key(word, forced_language, force_refresh) in self._dedupe

    def add(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> LookupJob | None:
        key = self._key(word, forced_language, force_refresh)
        if key in self._dedupe:
            return None
        job = LookupJob(word, forced_language, force_refresh)
        self._pending[job.id] = job
        self._dedupe.add(key)
        self._total += 1
        return job

    def add_many(
        self,
        words: list[str],
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> tuple[int, int]:
        added = 0
        skipped = 0
        language_key = (forced_language or "").strip().lower()
        pending = self._pending
        dedupe = self._dedupe
        for word in words:
            key = (word.strip().lower(), language_key, force_refresh)
            if key in dedupe:
                skipped += 1
                continue
            job = LookupJob(word, forced_language, force_refresh)
            pending[job.id] = job
            dedupe.add(key)
            added += 1
        self._total += added
        return added, skipped

    def cancel(self, job_id: str) -> LookupJob | None:
        job = self._pending.pop(job_id, None)
        if job is None:
            job = self._failed.pop(job_id, None)
        if job is None:
            return None
        self._dedupe.discard(job.dedupe_key)
        self._total = max(0, self._total - 1)
        self._reset_total_if_empty()
        return job

    def start_next(self) -> LookupJob | None:
        if self._active is not None:
            return self._active
        if not self._pending:
            self._reset_total_if_empty()
            return None
        _job_id, job = self._pending.popitem(last=False)
        job.status = LookupJobStatus.RUNNING
        self._active = job
        return job

    def progress_index(self) -> int:
        return max(1, self._total - len(self._pending))

    def complete_active(self) -> LookupJob | None:
        job = self._active
        if job is None:
            return None
        self._active = None
        self._dedupe.discard(job.dedupe_key)
        self._reset_total_if_empty()
        return job

    def fail_active(self) -> LookupJob | None:
        job = self._active
        if job is None:
            return None
        self._active = None
        job.status = LookupJobStatus.FAILED
        self._failed = OrderedDict([(job.id, job), *self._failed.items()])
        return job

    def set_active_language(self, language: str) -> None:
        job = self._active
        if job is None:
            return
        old_key = job.dedupe_key
        job.forced_language = language
        self._dedupe.discard(old_key)
        self._dedupe.add(job.dedupe_key)

    def correct_active_word(self, word: str, language: str) -> bool:
        """Replace a user-selected typo while preserving its queue position."""
        job = self._active
        if job is None:
            return False
        for forced in (language, ""):
            key = self._key(word, forced, job.force_refresh)
            if key != job.dedupe_key and key in self._dedupe:
                return False
        self._dedupe.discard(job.dedupe_key)
        job.word = word
        job.forced_language = language
        self._dedupe.add(job.dedupe_key)
        return True

    def retry(self, job_id: str) -> LookupJob | None:
        job = self._failed.pop(job_id, None)
        if job is None:
            return None
        job.status = LookupJobStatus.PENDING
        self._pending = OrderedDict([(job.id, job), *self._pending.items()])
        return job

    def retry_all(self) -> int:
        if not self._failed:
            return 0
        retrying = list(self._failed.items())
        self._failed.clear()
        for _job_id, job in retrying:
            job.status = LookupJobStatus.PENDING
        self._pending = OrderedDict([*retrying, *self._pending.items()])
        return len(retrying)

    def clear_failed(self) -> int:
        removed = len(self._failed)
        for job in self._failed.values():
            self._dedupe.discard(job.dedupe_key)
        self._failed.clear()
        self._total = max(0, self._total - removed)
        self._reset_total_if_empty()
        return removed

    def stop(self) -> None:
        """Cancel unfinished jobs, retaining failures for an explicit retry."""
        self._pending.clear()
        self._active = None
        self._dedupe = {job.dedupe_key for job in self._failed.values()}
        self._total = len(self._failed)

    def abort(self) -> None:
        self._pending.clear()
        self._failed.clear()
        self._active = None
        self._dedupe.clear()
        self._total = 0

    def rows(self) -> list[LookupJob]:
        rows: list[LookupJob] = []
        if self._active is not None:
            rows.append(self._active)
        rows.extend(self._failed.values())
        rows.extend(self._pending.values())
        return rows

    def _reset_total_if_empty(self) -> None:
        if self._active is None and not self._pending and not self._failed:
            self._total = 0

    @staticmethod
    def _key(
        word: str,
        forced_language: str,
        force_refresh: bool,
    ) -> tuple[str, str, bool]:
        return (
            word.strip().lower(),
            (forced_language or "").strip().lower(),
            force_refresh,
        )
