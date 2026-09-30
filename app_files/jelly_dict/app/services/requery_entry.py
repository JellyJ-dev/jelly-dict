from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from app.core.domain import EntryPatch, EntryRef, WorkbookRevision
from app.core.models import VocabularyEntry
from app.services.lookup_service import LookupOutcome
from app.services.ports import WorkbookRepositoryPort


@dataclass(frozen=True)
class RequeryPlan:
    path: Path
    language: str
    original_key: str
    lookup_word: str
    ref: EntryRef
    revision: WorkbookRevision
    original_json: str
    current_json: str
    original_key_has_other_rows: bool = False

    @property
    def original_entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.original_json)

    @property
    def current_entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.current_json)


@dataclass(frozen=True)
class RequeryCommitResult:
    status: Literal["updated", "not_found"]
    entry_json: str
    backup_path: Path | None = None
    revision: WorkbookRevision | None = None
    ref: EntryRef | None = None
    retired_original_key: bool = False

    @property
    def entry(self) -> VocabularyEntry:
        return VocabularyEntry.from_json(self.entry_json)


class RequeryEntryUseCase:
    def __init__(self, repository: WorkbookRepositoryPort) -> None:
        self._repository = repository

    def prepare(
        self,
        path: Path,
        language: str,
        original_key: str,
        current: VocabularyEntry,
        *,
        ref: EntryRef | None = None,
    ) -> RequeryPlan | None:
        snapshot = self._repository.read_snapshot(path)
        row = (
            snapshot.find_ref(ref)
            if ref is not None
            else snapshot.find_key(
                language,
                original_key,
            )
        )
        if row is None:
            return None
        return RequeryPlan(
            path=path,
            language=language,
            original_key=original_key,
            lookup_word=current.word.strip(),
            ref=row.ref,
            revision=snapshot.revision,
            original_json=row.entry.to_json(),
            current_json=current.to_json(),
            original_key_has_other_rows=any(
                candidate.ref != row.ref
                and candidate.ref.language == language
                and candidate.ref.word_key == original_key
                for candidate in snapshot.rows
            ),
        )

    def commit(
        self,
        plan: RequeryPlan,
        lookup: LookupOutcome,
        columns: Sequence[str],
    ) -> RequeryCommitResult:
        result = lookup.result
        if not result.ok or result.entry is None:
            return RequeryCommitResult(
                "not_found",
                plan.original_json,
                revision=plan.revision,
                ref=plan.ref,
            )

        original = plan.original_entry
        current = plan.current_entry
        refreshed = VocabularyEntry.from_dict(result.entry.to_dict())
        if result.suggested_word:
            refreshed.word = result.suggested_word
        refreshed.language = plan.language  # type: ignore[assignment]
        refreshed.id = original.id
        refreshed.created_at = original.created_at
        if current.tags:
            refreshed.tags = list(current.tags)
        if current.memo:
            refreshed.memo = current.memo
        refreshed.touch()

        committed = self._repository.commit_patch_with_backup(
            plan.path,
            plan.revision,
            [EntryPatch.replace(plan.ref, refreshed)],
            columns,
            backup_reason=f"requery-{plan.language}",
            refresh_snapshot=False,
        )
        if not committed.affected_refs:
            raise RuntimeError("재조회한 Excel 행을 찾을 수 없습니다.")
        refreshed_key = refreshed.word_key()
        retired_original_key = (
            refreshed_key != plan.original_key and not plan.original_key_has_other_rows
        )
        return RequeryCommitResult(
            "updated",
            refreshed.to_json(),
            committed.backup_path,
            committed.after_revision,
            committed.affected_refs[0],
            retired_original_key,
        )
