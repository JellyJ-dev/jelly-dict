from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.core.domain import EntryPatch, SavePreparation
from app.core.models import VocabularyEntry
from app.storage.excel_outcomes import WriteOutcome
from app.storage.excel_repository import WorkbookRepository

SaveResolver = Callable[
    [VocabularyEntry | None, VocabularyEntry],
    tuple[str, VocabularyEntry],
]


class ExcelWorkbookSaveAdapter:
    def __init__(self, repository: WorkbookRepository | None = None) -> None:
        self._repository = repository or WorkbookRepository()

    def prepare_save(
        self,
        path: Path,
        entry: VocabularyEntry,
    ) -> SavePreparation:
        snapshot = self._repository.read_snapshot(path)
        existing = snapshot.find_key(entry.language, entry.word_key())
        return SavePreparation(
            path=path,
            expected_revision=snapshot.revision,
            candidate=entry,
            existing=existing.entry if existing is not None else None,
            existing_ref=existing.ref if existing is not None else None,
        )

    def commit_prepared(
        self,
        preparation: SavePreparation,
        action: str,
        entry: VocabularyEntry,
        columns: list[str],
        *,
        backup_on_overwrite: bool = False,
    ) -> WriteOutcome:
        if action == "skip":
            checked = self._repository.commit_patch_without_snapshot(
                preparation.path,
                preparation.expected_revision,
                [],
                columns,
            )
            return WriteOutcome(
                action,
                preparation.existing or entry,
                entry_ref=preparation.existing_ref,
                revision=checked.after_revision,
            )

        patch = (
            EntryPatch.replace(preparation.existing_ref, entry)
            if action == "overwrite" and preparation.existing_ref is not None
            else EntryPatch.append(entry)
        )
        if action == "overwrite" and backup_on_overwrite:
            committed = self._repository.commit_patch_with_backup(
                preparation.path,
                preparation.expected_revision,
                [patch],
                columns,
                backup_reason=f"overwrite-{entry.language}",
                refresh_snapshot=False,
            )
        else:
            committed = self._repository.commit_patch_without_snapshot(
                preparation.path,
                preparation.expected_revision,
                [patch],
                columns,
            )
        return WriteOutcome(
            action,
            entry,
            committed.backup_path,
            committed.affected_refs[0],
            committed.after_revision,
        )

    def save_with_resolver(
        self,
        path: Path,
        entry: VocabularyEntry,
        columns: list[str],
        resolver: SaveResolver,
        *,
        backup_on_overwrite: bool = False,
    ) -> WriteOutcome:
        preparation = self.prepare_save(path, entry)
        action, resolved = resolver(preparation.existing, entry)
        return self.commit_prepared(
            preparation,
            action,
            resolved,
            columns,
            backup_on_overwrite=backup_on_overwrite,
        )
