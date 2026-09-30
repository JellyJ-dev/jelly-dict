from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

from openpyxl import load_workbook

from app.core import config
from app.core.diagnostics import diagnostic_operation
from app.core.errors import StorageError
from app.storage.workbook_revision import WorkbookRevision

log = logging.getLogger(__name__)

JOURNAL_SCHEMA_VERSION = 1
_HISTORY_LIMIT = 200


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class RecoveryRecord:
    schema_version: int
    operation_id: str
    workbook_path: str
    before_revision: WorkbookRevision
    after_revision: WorkbookRevision | None
    backup_path: str | None
    backup_revision: WorkbookRevision | None
    temp_path: str | None
    temp_revision: WorkbookRevision | None
    candidate_sha256: str | None
    commit_state: str
    started_at: str
    updated_at: str
    failure_type: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RecoveryRecord:
        schema_version = payload.get("schema_version")
        if not isinstance(schema_version, int):
            raise ValueError("schema_version must be an integer")

        def revision(name: str) -> WorkbookRevision | None:
            value = payload.get(name)
            if value is None:
                return None
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object")
            return WorkbookRevision(**value)

        before = revision("before_revision")
        if before is None:
            raise ValueError("before_revision is required")
        return cls(
            schema_version=schema_version,
            operation_id=str(payload["operation_id"]),
            workbook_path=str(payload["workbook_path"]),
            before_revision=before,
            after_revision=revision("after_revision"),
            backup_path=(
                str(payload["backup_path"]) if payload.get("backup_path") is not None else None
            ),
            backup_revision=revision("backup_revision"),
            temp_path=(str(payload["temp_path"]) if payload.get("temp_path") is not None else None),
            temp_revision=revision("temp_revision"),
            candidate_sha256=(
                str(payload["candidate_sha256"])
                if payload.get("candidate_sha256") is not None
                else None
            ),
            commit_state=str(payload["commit_state"]),
            started_at=str(payload["started_at"]),
            updated_at=str(payload["updated_at"]),
            failure_type=(
                str(payload["failure_type"]) if payload.get("failure_type") is not None else None
            ),
        )


@dataclass(frozen=True)
class RecoverySummary:
    inspected: int = 0
    committed: int = 0
    rolled_back: int = 0
    restored_from_backup: int = 0
    ambiguous: int = 0
    invalid_journals: int = 0


class WorkbookRecoveryJournal:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else config.workbook_recovery_dir()
        self.active_dir = self.root / "active"
        self.history_dir = self.root / "history"

    def begin(
        self,
        workbook_path: Path,
        before_revision: WorkbookRevision,
        backup_path: Path | None = None,
    ) -> WorkbookMutationJournal:
        self._ensure_dirs()
        operation_id = uuid.uuid4().hex
        now = _utc_now()
        resolved_workbook = Path(workbook_path).expanduser().resolve(strict=False)
        resolved_backup = (
            Path(backup_path).expanduser().resolve(strict=False)
            if backup_path is not None
            else None
        )
        record = RecoveryRecord(
            schema_version=JOURNAL_SCHEMA_VERSION,
            operation_id=operation_id,
            workbook_path=str(resolved_workbook),
            before_revision=before_revision,
            after_revision=None,
            backup_path=str(resolved_backup) if resolved_backup is not None else None,
            backup_revision=(
                WorkbookRevision.capture(resolved_backup) if resolved_backup is not None else None
            ),
            temp_path=None,
            temp_revision=None,
            candidate_sha256=None,
            commit_state="prepared",
            started_at=now,
            updated_at=now,
        )
        active_path = self.active_dir / f"{operation_id}.json"
        self._write_record(active_path, record)
        return WorkbookMutationJournal(self, active_path, record)

    def recover_all(self) -> RecoverySummary:
        self._ensure_dirs()
        summary = RecoverySummary()
        for journal_path in sorted(self.active_dir.glob("*.json")):
            summary = replace(summary, inspected=summary.inspected + 1)
            try:
                record = self._read_record(journal_path)
                self._validate_record(journal_path, record)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.error("invalid workbook recovery journal %s: %s", journal_path, exc)
                summary = replace(
                    summary,
                    invalid_journals=summary.invalid_journals + 1,
                )
                continue
            try:
                outcome = self._recover_one(journal_path, record)
            except (OSError, StorageError) as exc:
                log.error(
                    "workbook recovery operation %s failed safely: %s",
                    record.operation_id,
                    exc,
                )
                outcome = "ambiguous"
            if outcome == "recovered_committed":
                summary = replace(summary, committed=summary.committed + 1)
            elif outcome == "recovered_rolled_back":
                summary = replace(summary, rolled_back=summary.rolled_back + 1)
            elif outcome == "recovered_from_backup":
                summary = replace(
                    summary,
                    restored_from_backup=summary.restored_from_backup + 1,
                )
            else:
                summary = replace(summary, ambiguous=summary.ambiguous + 1)
        return summary

    def _recover_one(self, journal_path: Path, record: RecoveryRecord) -> str:
        workbook_path = Path(record.workbook_path)
        with _workbook_lock(workbook_path):
            current = WorkbookRevision.capture(workbook_path)
            original_valid = not current.exists or _is_valid_workbook(workbook_path)
            temp_path = Path(record.temp_path) if record.temp_path else None
            temp_valid = (
                temp_path is None or not temp_path.exists() or _is_valid_workbook(temp_path)
            )
            backup_path = Path(record.backup_path) if record.backup_path else None
            backup_valid = (
                backup_path is None or not backup_path.exists() or _is_valid_workbook(backup_path)
            )
            if not original_valid or not temp_valid or not backup_valid:
                log.warning(
                    "workbook recovery validation found an invalid artifact for operation %s",
                    record.operation_id,
                )
            if current == record.before_revision:
                self._remove_owned_temp(record)
                self._archive(
                    journal_path,
                    replace(
                        record,
                        commit_state="recovered_rolled_back",
                        updated_at=_utc_now(),
                    ),
                )
                log.info("rolled back incomplete workbook operation %s", record.operation_id)
                return "recovered_rolled_back"

            if self._is_committed_candidate(workbook_path, record):
                self._remove_owned_temp(record)
                self._archive(
                    journal_path,
                    replace(
                        record,
                        after_revision=current,
                        commit_state="recovered_committed",
                        updated_at=_utc_now(),
                    ),
                )
                log.info("confirmed committed workbook operation %s", record.operation_id)
                return "recovered_committed"

            if not current.exists and not record.before_revision.exists:
                self._remove_owned_temp(record)
                self._archive(
                    journal_path,
                    replace(
                        record,
                        commit_state="recovered_rolled_back",
                        updated_at=_utc_now(),
                    ),
                )
                return "recovered_rolled_back"

            if (
                not current.exists
                and backup_path is not None
                and self._backup_matches_before(record, backup_path)
                and backup_valid
            ):
                self._restore_backup(backup_path, workbook_path)
                restored = WorkbookRevision.capture(workbook_path)
                self._remove_owned_temp(record)
                self._archive(
                    journal_path,
                    replace(
                        record,
                        after_revision=restored,
                        commit_state="recovered_from_backup",
                        updated_at=_utc_now(),
                    ),
                )
                log.warning(
                    "restored missing workbook from transaction backup for operation %s",
                    record.operation_id,
                )
                return "recovered_from_backup"

            log.error(
                "ambiguous workbook recovery operation %s; files left untouched",
                record.operation_id,
            )
            return "ambiguous"

    def _is_committed_candidate(self, path: Path, record: RecoveryRecord) -> bool:
        current = WorkbookRevision.capture(path)
        if not current.exists or not _is_valid_workbook(path):
            return False
        if record.after_revision is not None and current == record.after_revision:
            return True
        if not record.candidate_sha256:
            return False
        try:
            return _sha256(path) == record.candidate_sha256
        except OSError:
            return False

    @staticmethod
    def _backup_matches_before(record: RecoveryRecord, backup_path: Path) -> bool:
        backup = WorkbookRevision.capture(backup_path)
        recorded = record.backup_revision
        if recorded is None or backup != recorded or not backup.exists:
            return False
        before = record.before_revision
        return bool(backup.size == before.size and backup.mtime_ns == before.mtime_ns)

    @staticmethod
    def _restore_backup(backup_path: Path, workbook_path: Path) -> None:
        workbook_path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                dir=workbook_path.parent,
                prefix=f".{workbook_path.stem}.recovery.",
                suffix=workbook_path.suffix,
            ) as temp_file:
                temp_name = temp_file.name
            temp_path = Path(temp_name)
            shutil.copy2(backup_path, temp_path)
            if not _is_valid_workbook(temp_path):
                raise StorageError("Workbook recovery backup validation failed")
            temp_path.replace(workbook_path)
        except OSError as exc:
            raise StorageError(f"Workbook recovery failed: {exc}") from exc
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    def _remove_owned_temp(self, record: RecoveryRecord) -> None:
        if record.temp_path is None:
            return
        temp_path = Path(record.temp_path)
        workbook_path = Path(record.workbook_path)
        if not _is_owned_temp(temp_path, workbook_path):
            return
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("failed to remove recovered workbook temp %s: %s", temp_path, exc)

    def _validate_record(self, journal_path: Path, record: RecoveryRecord) -> None:
        if record.schema_version != JOURNAL_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version {record.schema_version}")
        if journal_path.stem != record.operation_id:
            raise ValueError("operation id does not match journal filename")
        if not record.operation_id or any(
            ch not in "0123456789abcdef" for ch in record.operation_id
        ):
            raise ValueError("invalid operation id")
        workbook_path = Path(record.workbook_path)
        if not workbook_path.is_absolute():
            raise ValueError("workbook path must be absolute")
        if record.before_revision.resolved_path != str(workbook_path):
            raise ValueError("before revision path mismatch")
        if record.temp_path is not None and not _is_owned_temp(
            Path(record.temp_path), workbook_path
        ):
            raise ValueError("temporary workbook path is not owned")
        if record.backup_path is not None and not _is_owned_backup(
            Path(record.backup_path), workbook_path
        ):
            raise ValueError("backup path is not owned")

    def _archive(self, active_path: Path, record: RecoveryRecord) -> None:
        self._write_record(self.history_dir / active_path.name, record)
        try:
            active_path.unlink()
        except OSError as exc:
            log.warning("failed to remove active workbook journal %s: %s", active_path, exc)
            return
        self._trim_history()

    def _trim_history(self) -> None:
        try:
            records = sorted(
                self.history_dir.glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for stale in records[_HISTORY_LIMIT:]:
                stale.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("failed to trim workbook recovery history: %s", exc)

    def _ensure_dirs(self) -> None:
        try:
            self.active_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.history_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise StorageError(f"Workbook recovery journal unavailable: {exc}") from exc

    @staticmethod
    def _read_record(path: Path) -> RecoveryRecord:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("journal root must be an object")
        return RecoveryRecord.from_dict(payload)

    def _write_record(self, path: Path, record: RecoveryRecord) -> None:
        temp_name = ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            encoded = json.dumps(
                record.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as temp_file:
                temp_name = temp_file.name
                os.chmod(temp_name, 0o600)
                temp_file.write(encoded)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            Path(temp_name).replace(path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise StorageError(f"Workbook recovery journal write failed: {exc}") from exc
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)


class WorkbookMutationJournal:
    def __init__(
        self,
        owner: WorkbookRecoveryJournal,
        active_path: Path,
        record: RecoveryRecord,
    ) -> None:
        self._owner = owner
        self._active_path = active_path
        self.record = record

    def temp_created(self, temp_path: Path) -> None:
        record = replace(
            self.record,
            commit_state="temp_created",
            temp_path=str(temp_path.resolve()),
            updated_at=_utc_now(),
        )
        self._owner._write_record(self._active_path, record)
        self.record = record

    def ready_to_commit(self, temp_path: Path) -> None:
        revision = WorkbookRevision.capture(temp_path)
        record = replace(
            self.record,
            commit_state="ready_to_commit",
            temp_path=str(temp_path.resolve()),
            temp_revision=revision,
            candidate_sha256=_sha256(temp_path),
            updated_at=_utc_now(),
        )
        self._owner._write_record(self._active_path, record)
        self.record = record

    def committed(self, after_revision: WorkbookRevision) -> None:
        record = replace(
            self.record,
            after_revision=after_revision,
            commit_state="committed",
            updated_at=_utc_now(),
        )
        try:
            self._owner._write_record(self._active_path, record)
            self._owner._archive(self._active_path, record)
            self.record = record
        except StorageError as exc:
            log.critical(
                "workbook committed but recovery journal finalization failed for %s: %s",
                self.record.operation_id,
                exc,
            )

    def failed(self, exc: BaseException) -> None:
        record = replace(
            self.record,
            commit_state="failed",
            failure_type=type(exc).__name__,
            updated_at=_utc_now(),
        )
        try:
            self._owner._archive(self._active_path, record)
            self.record = record
        except StorageError as journal_exc:
            log.error(
                "failed to archive workbook transaction failure %s: %s",
                self.record.operation_id,
                journal_exc,
            )


def recover_pending_workbook_transactions(
    root: Path | None = None,
) -> RecoverySummary:
    with diagnostic_operation("recovery") as diagnostic:
        summary = WorkbookRecoveryJournal(root).recover_all()
        result = (
            "conflict"
            if summary.ambiguous or summary.invalid_journals
            else ("empty" if not summary.inspected else "success")
        )
        diagnostic.finish(result, row_count=summary.inspected)
        return summary


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid_workbook(path: Path) -> bool:
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
        workbook.close()
        return True
    except Exception:
        return False


def _is_owned_temp(temp_path: Path, workbook_path: Path) -> bool:
    try:
        temp = temp_path.expanduser().resolve(strict=False)
        workbook = workbook_path.expanduser().resolve(strict=False)
    except OSError:
        return False
    return (
        temp.parent == workbook.parent
        and temp.name.startswith(f".{workbook.stem}.")
        and temp.suffix == workbook.suffix
    )


def _is_owned_backup(backup_path: Path, workbook_path: Path) -> bool:
    try:
        backup = backup_path.expanduser().resolve(strict=False)
        workbook = workbook_path.expanduser().resolve(strict=False)
    except OSError:
        return False
    return (
        backup.parent == workbook.parent / "Jelly Dict Backups"
        and backup.suffix == workbook.suffix
        and backup.name.startswith(f"{workbook.stem}.")
    )


@contextmanager
def _workbook_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.jelly.lock")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
