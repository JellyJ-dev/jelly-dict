"""Qt-free wordbook use cases backed by narrow application ports."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.domain import EntryPatch, EntryRef, WorkbookRevision
from app.core.models import VocabularyEntry, normalize_word_key
from app.core.settings import (
    AppSettings,
    PathSettings,
    SettingsDraft,
    settings_snapshot,
)
from app.services.entry_projection_service import EntryProjectionService
from app.services.ports import (
    AnkiSyncPort,
    LookupCachePort,
    PathSettingsPort,
    SavePolicySettingsPort,
    WorkbookRepositoryPort,
)
from app.services.requery_entry import RequeryCommitResult, RequeryEntryUseCase

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordbookDeleteResult:
    removed: int
    backup_path: Path | None
    rows: tuple[Any, ...]
    before_revision: Any
    after_revision: Any
    cache_snapshot: tuple[VocabularyEntry, ...]
    recent_snapshot: tuple[Any, ...]
    saved_projection_snapshot: tuple[Any, ...]
    cleanup_keys: frozenset[str]
    anki_words: tuple[str, ...]
    deferred_anki_operation_id: str | None = None


@dataclass(frozen=True)
class WordbookEditResult:
    new_key: str
    entry: VocabularyEntry
    backup_path: Path | None
    old_ref: EntryRef
    new_ref: EntryRef | None


class WordbookService:
    def __init__(
        self,
        settings: AppSettings | SettingsDraft | PathSettings,
        repository: WorkbookRepositoryPort,
        cache: LookupCachePort,
        anki_sync: AnkiSyncPort,
        policy_settings: SavePolicySettingsPort | None = None,
    ) -> None:
        if policy_settings is None:
            snapshot = settings_snapshot(settings, validate=False)  # type: ignore[arg-type]
            self._paths: PathSettingsPort = snapshot.paths
            self._policy: SavePolicySettingsPort = snapshot.lookup
        else:
            self._paths = settings
            self._policy = policy_settings
        self._repository = repository
        self._cache = cache
        self._anki_sync = anki_sync
        self._projection = EntryProjectionService()
        self._requery = RequeryEntryUseCase(repository)
        self._snapshots: dict[str, Any] = {}
        self._saved_words: set[tuple[str, str]] = set()
        self._session_anki_operations: set[str] = set()

    def update_settings(
        self,
        settings: AppSettings | SettingsDraft | PathSettings,
        anki_sync: AnkiSyncPort,
        policy_settings: SavePolicySettingsPort | None = None,
    ) -> None:
        if policy_settings is None:
            snapshot = settings_snapshot(settings, validate=False)  # type: ignore[arg-type]
            self._paths = snapshot.paths
            self._policy = snapshot.lookup
        else:
            self._paths = settings
            self._policy = policy_settings
        self._anki_sync = anki_sync
        self._snapshots.clear()

    def snapshot(self, language: str):
        language = language if language in ("en", "ja") else "en"
        path = Path(self._paths.excel_path_for(language))
        revision = WorkbookRevision.capture(path)
        current = self._snapshots.get(language)
        if (
            current is not None
            and current.path == path.expanduser()
            and current.revision == revision
        ):
            return current
        snapshot = self._repository.read_snapshot(path)
        self._snapshots[language] = snapshot
        return snapshot

    def refresh_saved_words(self) -> set[tuple[str, str]]:
        saved: set[tuple[str, str]] = set()
        for language in ("en", "ja"):
            try:
                snapshot = self.snapshot(language)
            except Exception as exc:
                log.warning("saved word snapshot failed: %s", exc)
                continue
            for row in snapshot.rows:
                entry = row.entry
                if entry.language == language and entry.word.strip():
                    saved.add((language, row.ref.word_key))
        self._saved_words = saved
        return set(saved)

    def set_saved_words(self, saved_words: set[tuple[str, str]]) -> None:
        self._saved_words = set(saved_words)

    def is_saved(self, word: str, language: str) -> bool:
        return (language, normalize_word_key(word, language)) in self._saved_words

    def edit_context(
        self,
        language: str,
        word: str,
        *,
        ref: EntryRef | None = None,
    ) -> tuple[Any, WorkbookRevision] | None:
        """Return the current row and revision needed by the edit dialog.

        The controller should not read a workbook just to open an editor.  Keeping
        this lookup here also makes the revision captured for the dialog explicit,
        so the eventual save can reject an external workbook change safely.
        """
        snapshot = self.snapshot(language)
        row = (
            snapshot.find_ref(ref)
            if ref is not None
            else snapshot.find_key(language, normalize_word_key(word, language))
        )
        if row is None:
            return None
        return row, snapshot.revision

    def list_entries(
        self,
        language: str,
        sort_option: str = "최신순",
    ) -> list[tuple[EntryRef, VocabularyEntry]]:
        return [
            (ref, entry)
            for ref, entry, _search_blob in self.list_indexed_entries(language, sort_option)
        ]

    def list_indexed_entries(
        self,
        language: str,
        sort_option: str = "최신순",
    ) -> list[tuple[EntryRef, VocabularyEntry, str]]:
        snapshot = self.snapshot(language)
        entries = []
        for row in snapshot.rows:
            if row.ref.language != language:
                continue
            entry = row.entry
            if entry.word.strip():
                entries.append((row.ref, entry, row.search_blob))
        if sort_option == "가나다순":
            entries.sort(key=lambda item: item[1].word.lower())
        elif sort_option == "최신순":
            entries.reverse()
        return entries

    def delete_words(self, language: str, words: list[str]) -> WordbookDeleteResult:
        keys = {
            normalize_word_key(word, language)
            for word in words
            if isinstance(word, str) and word.strip()
        }
        snapshot = self.snapshot(language)
        result = self._repository.delete_matching_rows(
            Path(self._paths.excel_path_for(language)),
            snapshot.revision,
            language,
            keys,
        )
        return self._finish_delete(
            language,
            Path(self._paths.excel_path_for(language)),
            result,
            keys,
            tuple(words),
        )

    def delete_refs(
        self,
        language: str,
        refs: tuple[EntryRef, ...],
    ) -> WordbookDeleteResult:
        path = Path(self._paths.excel_path_for(language))
        snapshot = self.snapshot(language)
        if any(snapshot.find_ref(ref) is None for ref in refs):
            raise LookupError("삭제할 단어를 찾을 수 없습니다.")
        selected = set(refs)
        selected_keys = {ref.word_key for ref in refs}
        remaining_keys = {
            row.ref.word_key
            for row in snapshot.rows
            if row.ref.language == language and row.ref not in selected
        }
        cleanup_keys = selected_keys - remaining_keys
        words_by_key = {
            row.ref.word_key: row.entry.word for row in snapshot.rows if row.ref in selected
        }
        anki_words = tuple(words_by_key[key] for key in sorted(cleanup_keys) if key in words_by_key)
        result = self._repository.delete_rows(path, snapshot.revision, refs)
        return self._finish_delete(
            language,
            path,
            result,
            cleanup_keys,
            anki_words,
        )

    def _finish_delete(
        self,
        language: str,
        path: Path,
        result: Any,
        cleanup_keys: set[str],
        anki_words: tuple[str, ...],
    ) -> WordbookDeleteResult:
        refs = tuple(row.ref for row in result.rows)
        cache_snapshot, recent_snapshot = self._snapshot_delete_state(
            language,
            cleanup_keys,
        )
        saved_snapshot = self._snapshot_saved_projections(path, refs)
        try:
            self._delete_saved_projections(path, refs)
            self._shift_saved_projections_after_delete(
                path,
                (row.original_row_number for row in result.rows),
            )
        except Exception as exc:
            log.warning("saved projection cleanup failed: %s", exc)
        if cleanup_keys:
            try:
                self._cache.delete_entries(language, cleanup_keys)
                delete_recent = getattr(self._cache, "delete_recent_entries", None)
                if callable(delete_recent):
                    delete_recent(language, cleanup_keys)
            except Exception as exc:
                log.warning("cache cleanup after wordbook delete failed: %s", exc)
            self._saved_words.difference_update((language, key) for key in cleanup_keys)
        self._snapshots.pop(language, None)
        operation_id = self._enqueue_anki(path, list(anki_words), language)
        return WordbookDeleteResult(
            removed=result.removed,
            backup_path=result.backup_path,
            rows=tuple(result.rows),
            before_revision=result.before_revision,
            after_revision=result.after_revision,
            cache_snapshot=cache_snapshot,
            recent_snapshot=recent_snapshot,
            saved_projection_snapshot=saved_snapshot,
            cleanup_keys=frozenset(cleanup_keys),
            anki_words=anki_words,
            deferred_anki_operation_id=operation_id,
        )

    def undo_delete(
        self,
        result: WordbookDeleteResult,
        language: str,
        path: Path,
    ) -> int:
        current = self._repository.read_snapshot(path)
        restored = self._repository.restore_rows(path, current.revision, result.rows)
        self._snapshots.pop(language, None)
        try:
            if result.cache_snapshot:
                for entry in result.cache_snapshot:
                    self._cache.upsert(entry)
            elif result.cleanup_keys:
                for row in self.snapshot(language).rows:
                    if row.ref.word_key in result.cleanup_keys:
                        self._cache.upsert(row.entry)
            restore_recent = getattr(self._cache, "restore_recent_lookups", None)
            if result.recent_snapshot and callable(restore_recent):
                restore_recent(result.recent_snapshot)
            shift_insert = getattr(
                self._cache,
                "shift_saved_projections_for_insert",
                None,
            )
            if restored.restored_row_numbers and callable(shift_insert):
                shift_insert(path, restored.restored_row_numbers)
            restore_saved = getattr(self._cache, "restore_saved_projections", None)
            if result.saved_projection_snapshot and callable(restore_saved):
                restore_saved(result.saved_projection_snapshot)
        except Exception as exc:
            log.warning("cache restore after wordbook undo failed: %s", exc)
        self.refresh_saved_words()
        return restored.restored + restored.skipped_existing

    def save_edit(
        self,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
        *,
        target_ref: EntryRef | None = None,
        expected_revision: Any | None = None,
        create_backup: bool = True,
    ) -> WordbookEditResult:
        if not entry.word.strip():
            raise ValueError("단어는 비울 수 없습니다.")
        path = Path(self._paths.excel_path_for(language))
        snapshot = self.snapshot(language)
        if expected_revision is not None and snapshot.revision != expected_revision:
            raise RuntimeError("Excel 파일이 외부에서 변경되었습니다.")
        original = (
            snapshot.find_ref(target_ref)
            if target_ref is not None
            else snapshot.find_key(language, original_key)
        )
        if original is None:
            raise LookupError("수정할 단어를 찾을 수 없습니다.")
        new_key = normalize_word_key(entry.word, language)
        if new_key != original_key:
            collision = snapshot.find_key(language, new_key)
            if collision is not None and collision.ref != original.ref:
                raise ValueError("같은 단어가 이미 단어장에 있습니다.")
        old_key_remains = any(
            row.ref != original.ref
            and row.ref.language == language
            and row.ref.word_key == original_key
            for row in snapshot.rows
        )
        patch = EntryPatch.replace(original.ref, entry)
        if create_backup:
            committed = self._repository.commit_patch_with_backup(
                path,
                snapshot.revision,
                [patch],
                list(self._policy.excel_columns),
                backup_reason=f"edit-{language}",
                refresh_snapshot=False,
            )
        else:
            committed = self._repository.commit_patch_without_snapshot(
                path,
                snapshot.revision,
                [patch],
                list(self._policy.excel_columns),
            )
        new_ref = committed.affected_refs[0]
        try:
            if new_key != original_key and not old_key_remains:
                self._cache.delete_entries(language, {original_key})
                delete_recent = getattr(self._cache, "delete_recent_entries", None)
                if callable(delete_recent):
                    delete_recent(language, {original_key})
            self._replace_saved_projection(path, original.ref, new_ref, entry)
        except Exception as exc:
            log.warning("projection update after wordbook edit failed: %s", exc)
        self._snapshots.pop(language, None)
        self.refresh_saved_words()
        return WordbookEditResult(
            new_key,
            entry,
            committed.backup_path,
            original.ref,
            new_ref,
        )

    def prepare_requery(
        self,
        path: Path,
        language: str,
        key: str,
        current: VocabularyEntry,
        ref: EntryRef | None = None,
    ):
        return self._requery.prepare(path, language, key, current, ref=ref)

    def commit_requery(self, plan, lookup, columns: list[str]) -> RequeryCommitResult:
        committed = self._requery.commit(plan, lookup, columns)
        if committed.status != "updated":
            return committed
        entry = committed.entry
        try:
            if committed.retired_original_key:
                self._cache.delete_entries(plan.language, {plan.original_key})
                delete_recent = getattr(self._cache, "delete_recent_entries", None)
                if callable(delete_recent):
                    delete_recent(plan.language, {plan.original_key})
            self._replace_saved_projection(plan.path, plan.ref, committed.ref, entry)
            remember = getattr(self._cache, "remember_lookup", None)
            if callable(remember):
                remember(plan.lookup_word, plan.language, entry_word=entry.word)
        except Exception as exc:
            log.warning("projection update after wordbook requery failed: %s", exc)
        self._snapshots.pop(plan.language, None)
        self.refresh_saved_words()
        return committed

    def saved_entry_projection(
        self,
        word: str,
        language: str,
        lookup_cached: VocabularyEntry | None = None,
    ) -> VocabularyEntry | None:
        path = Path(self._paths.excel_path_for(language))
        snapshot = self.snapshot(language)
        latest = getattr(self._cache, "latest_saved_projection", None)
        if callable(latest):
            record = latest(path, word, language)
            row = snapshot.find_ref(record.ref) if record is not None else None
            if row is not None:
                return self._projection.project_saved(row.entry, record.entry)
        row = snapshot.find_key(language, normalize_word_key(word, language))
        if row is None:
            return lookup_cached
        enrichment = lookup_cached
        get_saved = getattr(self._cache, "get_saved_projection", None)
        if callable(get_saved):
            enrichment = get_saved(path, row.ref) or lookup_cached
        return self._projection.project_saved(row.entry, enrichment)

    def _snapshot_delete_state(self, language: str, keys: set[str]):
        cached: list[VocabularyEntry] = []
        get_entry = getattr(self._cache, "get", None)
        if callable(get_entry):
            for key in keys:
                try:
                    entry = get_entry(key, language)
                except Exception as exc:
                    log.warning("cache snapshot failed: %s", exc)
                    continue
                if entry is not None:
                    cached.append(VocabularyEntry.from_dict(entry.to_dict()))
        recent: list[Any] = []
        snapshot_recent = getattr(self._cache, "snapshot_recent_lookups", None)
        if callable(snapshot_recent):
            try:
                for row in snapshot_recent():
                    row_language, typed_word, entry_word, _timestamp = row
                    if row_language != language:
                        continue
                    typed_key = normalize_word_key(typed_word, language)
                    entry_key = normalize_word_key(entry_word, language) if entry_word else ""
                    if typed_key in keys or entry_key in keys:
                        recent.append(row)
            except Exception as exc:
                log.warning("recent lookup snapshot failed: %s", exc)
        return tuple(cached), tuple(recent)

    def _snapshot_saved_projections(self, path: Path, refs: tuple[EntryRef, ...]):
        method = getattr(self._cache, "snapshot_saved_projections", None)
        return tuple(method(path, refs)) if refs and callable(method) else ()

    def _delete_saved_projections(self, path: Path, refs: tuple[EntryRef, ...]) -> None:
        method = getattr(self._cache, "delete_saved_projection_refs", None)
        if refs and callable(method):
            method(path, refs)

    def _shift_saved_projections_after_delete(self, path: Path, rows) -> None:
        method = getattr(self._cache, "shift_saved_projections_after_delete", None)
        if callable(method):
            method(path, rows)

    def _replace_saved_projection(
        self,
        path: Path,
        old_ref: EntryRef,
        new_ref: EntryRef,
        entry: VocabularyEntry,
    ) -> None:
        upsert = getattr(self._cache, "upsert_saved_projection", None)
        if callable(upsert):
            delete = getattr(self._cache, "delete_saved_projection_refs", None)
            if callable(delete):
                delete(path, (old_ref,))
            upsert(path, new_ref, entry)
        else:
            self._cache.upsert(entry)

    def _enqueue_anki(
        self,
        path: Path,
        words: list[str],
        language: str,
    ) -> str | None:
        if not words or not self._anki_sync.enabled:
            return None
        enqueue = getattr(self._cache, "enqueue_anki_delete", None)
        if not callable(enqueue):
            return None
        try:
            operation_id = enqueue(path, words, language)
        except Exception as exc:
            log.warning("Anki delete outbox enqueue failed: %s", exc)
            return None
        self._session_anki_operations.add(operation_id)
        return operation_id

    def cancel_anki_delete(self, operation_id: str | None) -> None:
        if operation_id is None:
            return
        cancel = getattr(self._cache, "cancel_anki_delete", None)
        if callable(cancel):
            try:
                cancel(operation_id)
            except Exception as exc:
                log.warning("Anki delete outbox cancel failed: %s", exc)
        self._session_anki_operations.discard(operation_id)

    def commit_anki_delete(
        self,
        words: list[str],
        language: str,
        operation_id: str | None = None,
    ) -> tuple[int, list[str]]:
        if not words or not self._anki_sync.enabled:
            return 0, []
        try:
            removed, errors = self._anki_sync.delete_words(words, language)
        except Exception as exc:
            errors = [str(exc)]
            removed = 0
        if operation_id is not None:
            if errors:
                fail = getattr(self._cache, "fail_anki_delete", None)
                if callable(fail):
                    try:
                        fail(operation_id, "; ".join(errors[:5]))
                    except Exception as exc:
                        log.warning("Anki outbox failure update failed: %s", exc)
            else:
                complete = getattr(self._cache, "complete_anki_delete", None)
                if callable(complete):
                    try:
                        complete(operation_id)
                    except Exception as exc:
                        log.warning("Anki outbox completion failed: %s", exc)
            self._session_anki_operations.discard(operation_id)
        return removed, errors

    def retry_pending_anki_deletes(self) -> None:
        if not self._anki_sync.enabled:
            return
        pending = getattr(self._cache, "pending_anki_deletes", None)
        if not callable(pending):
            return
        for operation in pending(100):
            operation_id = getattr(operation, "operation_id", None)
            if not isinstance(operation_id, str) or operation_id in self._session_anki_operations:
                continue
            try:
                path = Path(operation.workbook_path)
                snapshot = self._repository.read_snapshot(path)
                existing = {
                    row.ref.word_key
                    for row in snapshot.rows
                    if row.ref.language == operation.language
                }
                keys = {normalize_word_key(word, operation.language) for word in operation.words}
            except Exception as exc:
                log.warning("Anki outbox validation failed: %s", exc)
                continue
            if existing & keys:
                self.cancel_anki_delete(operation_id)
                continue
            self.commit_anki_delete(
                list(operation.words),
                operation.language,
                operation_id,
            )
