from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtCore

from app.core.domain import EntryRef, WorkbookRevision
from app.core.errors import UnsupportedLanguageError
from app.core.models import VocabularyEntry, collect_examples_flat, wordbook_meaning_hint
from app.core.search_index import build_entry_search_blob
from app.services.lookup_service import LookupService
from app.services.requery_entry import RequeryPlan
from app.services.wordbook_service import WordbookDeleteResult, WordbookService
from app.ui.widgets.wordbook_items import WordbookDisplayItem

log = logging.getLogger(__name__)


def build_wordbook_items(
    service: WordbookService,
    language: str,
    sort_option: str,
) -> list[WordbookDisplayItem]:
    indexed = getattr(service, "list_indexed_entries", None)
    entries = (
        indexed(language, sort_option)
        if callable(indexed)
        else [
            (ref, entry, build_entry_search_blob(entry))
            for ref, entry in service.list_entries(language, sort_option)
        ]
    )
    return [
        WordbookDisplayItem(
            word=entry.word,
            language=language,
            reading=entry.reading or "",
            hint=wordbook_meaning_hint(entry, limit=160),
            tags=tuple(tag for tag in entry.tags if tag.strip()),
            memo=entry.memo or "",
            examples=_entry_example_texts(entry),
            updated_at=entry.updated_at or entry.created_at,
            entry_ref=ref,
            search_blob=search_blob,
        )
        for ref, entry, search_blob in entries
    ]


def _entry_example_texts(entry) -> tuple[str, ...]:
    examples = entry.examples_flat or collect_examples_flat(entry)
    texts: list[str] = []
    for example in examples:
        source = (example.source_text_plain or example.source_text or "").strip()
        translation = (example.translation_ko or "").strip()
        text = " ".join(part for part in (source, translation) if part)
        if text:
            texts.append(text)
    return tuple(texts)


class WordbookListWorker(QtCore.QObject):
    finished = QtCore.Signal(str, str, object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        service: WordbookService,
        language: str,
        sort_option: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._language = language
        self._sort_option = sort_option

    @QtCore.Slot()
    def run(self) -> None:
        try:
            items = build_wordbook_items(
                self._service,
                self._language,
                self._sort_option,
            )
        except Exception as exc:
            log.exception("wordbook list load failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(self._language, self._sort_option, items)


class WordbookDeleteWorker(QtCore.QObject):
    finished = QtCore.Signal(str, object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        service: WordbookService,
        language: str,
        words: list[str],
        refs: tuple[EntryRef, ...] | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._language = language
        self._words = words
        self._refs = refs

    @QtCore.Slot()
    def run(self) -> None:
        try:
            result = (
                self._service.delete_refs(self._language, self._refs)
                if self._refs
                else self._service.delete_words(self._language, self._words)
            )
        except Exception as exc:
            log.exception("wordbook delete failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(self._language, result)


class WordbookUndoWorker(QtCore.QObject):
    finished = QtCore.Signal(str, int)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        service: WordbookService,
        language: str,
        path: Path,
        result: WordbookDeleteResult,
        operation_id: str | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._language = language
        self._path = path
        self._result = result
        self._operation_id = operation_id

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self._service.cancel_anki_delete(self._operation_id)
            count = self._service.undo_delete(
                self._result,
                self._language,
                self._path,
            )
        except Exception as exc:
            log.exception("wordbook undo failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(self._language, count)


class WordbookEditWorker(QtCore.QObject):
    finished = QtCore.Signal(str, object)
    failed = QtCore.Signal(object)

    def __init__(
        self,
        service: WordbookService,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
        *,
        create_backup: bool,
        target_ref: EntryRef | None,
        expected_revision: WorkbookRevision | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._language = language
        self._original_key = original_key
        self._entry = entry
        self._create_backup = create_backup
        self._target_ref = target_ref
        self._expected_revision = expected_revision

    @QtCore.Slot()
    def run(self) -> None:
        try:
            result = self._service.save_edit(
                self._language,
                self._original_key,
                self._entry,
                target_ref=self._target_ref,
                expected_revision=self._expected_revision,
                create_backup=self._create_backup,
            )
        except Exception as exc:
            log.exception("wordbook edit commit failed")
            self.failed.emit(exc)
            return
        self.finished.emit(self._language, result)


class AnkiDeleteWorker(QtCore.QObject):
    finished = QtCore.Signal(int, object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        service: WordbookService,
        words: list[str],
        language: str,
        operation_id: str | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._words = words
        self._language = language
        self._operation_id = operation_id

    @QtCore.Slot()
    def run(self) -> None:
        try:
            removed, errors = self._service.commit_anki_delete(
                self._words,
                self._language,
                self._operation_id,
            )
        except Exception as exc:
            log.exception("Anki delete failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(removed, errors)


class AnkiRetryWorker(QtCore.QObject):
    finished = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, service: WordbookService) -> None:
        super().__init__()
        self._service = service

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self._service.retry_pending_anki_deletes()
        except Exception as exc:
            log.exception("Anki outbox retry failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit()


class RequeryWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        lookup_service: LookupService,
        service: WordbookService,
        plan: RequeryPlan,
        lookup_word: str,
        columns: list[str],
    ) -> None:
        super().__init__()
        self._lookup_service = lookup_service
        self._service = service
        self._plan = plan
        self._lookup_word = lookup_word
        self._columns = columns

    @QtCore.Slot()
    def run(self) -> None:
        try:
            outcome = self._lookup_service.lookup(
                self._lookup_word,
                self._plan.language,
                force_refresh=True,
                persist=False,
            )
            committed = self._service.commit_requery(
                self._plan,
                outcome,
                self._columns,
            )
        except UnsupportedLanguageError:
            self.failed.emit("입력 언어 미지원")
            return
        except Exception as exc:
            log.exception("wordbook requery failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(committed)
