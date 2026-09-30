"""Excel save flow including duplicate handling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.domain import EntryRef, SavePreparation, WorkbookRevision
from app.core.duplicate_checker import (
    DuplicateDecision,
    DuplicatePolicy,
    apply_policy,
    is_duplicate,
)
from app.core.models import VocabularyEntry
from app.core.settings import (
    AppSettings,
    PathSettings,
    SettingsDraft,
    settings_snapshot,
)
from app.services.ports import (
    PathSettingsPort,
    SavePolicySettingsPort,
    WorkbookSavePort,
)

log = logging.getLogger(__name__)

DuplicatePrompt = Callable[[VocabularyEntry, VocabularyEntry], DuplicateDecision]


@dataclass
class SaveOutcome:
    status: str  # "saved" | "updated" | "merged" | "kept" | "appended_new"
    path: Path
    entry: VocabularyEntry
    backup_path: Path | None = None
    entry_ref: EntryRef | None = None
    revision: WorkbookRevision | None = None


@dataclass(frozen=True)
class PreparedSave:
    preparation: SavePreparation
    policy: DuplicatePolicy | None
    decision_required: bool


class SaveService:
    def __init__(
        self,
        settings: AppSettings | SettingsDraft | PathSettings,
        workbook: WorkbookSavePort,
        duplicate_prompt: DuplicatePrompt | None = None,
        *,
        policy_settings: SavePolicySettingsPort | None = None,
    ) -> None:
        if policy_settings is None:
            snapshot = settings_snapshot(settings, validate=False)  # type: ignore[arg-type]
            self._paths: PathSettingsPort = snapshot.paths
            self._policy: SavePolicySettingsPort = snapshot.lookup
        else:
            self._paths = settings
            self._policy = policy_settings
        self._workbook = workbook
        self._prompt = duplicate_prompt
        self._session_policy: DuplicatePolicy | None = None

    def excel_path_for(self, language: str) -> Path:
        return Path(self._paths.excel_path_for(language)).expanduser()

    def reset_session_policy(self) -> None:
        self._session_policy = None

    def save(self, entry: VocabularyEntry) -> SaveOutcome:
        """Compatibility wrapper around prepare → decision → commit."""
        prepared = self.prepare(entry)
        decision = self.prompt_for_decision(prepared) if prepared.decision_required else None
        return self.commit(prepared, decision)

    def prepare(self, entry: VocabularyEntry) -> PreparedSave:
        """Read once and capture the exact workbook revision for commit."""
        path = self.excel_path_for(entry.language)
        path.parent.mkdir(parents=True, exist_ok=True)
        preparation = self._workbook.prepare_save(path, entry)
        existing = preparation.existing
        if existing is None or not is_duplicate(existing, entry):
            return PreparedSave(preparation, None, False)
        if self._session_policy is not None:
            return PreparedSave(preparation, self._session_policy, False)
        configured = self._policy.duplicate_policy
        if configured == "ask" and self._prompt is not None:
            return PreparedSave(preparation, None, True)
        policy: DuplicatePolicy = "update_existing" if configured == "ask" else configured  # type: ignore[assignment]
        return PreparedSave(preparation, policy, False)

    def prompt_for_decision(self, prepared: PreparedSave) -> DuplicateDecision:
        existing = prepared.preparation.existing
        candidate = prepared.preparation.candidate
        if not prepared.decision_required or existing is None or self._prompt is None:
            return DuplicateDecision(
                policy=prepared.policy or "update_existing",
                apply_for_session=False,
            )
        return self._prompt(existing, candidate)

    def commit(
        self,
        prepared: PreparedSave,
        decision: DuplicateDecision | None = None,
    ) -> SaveOutcome:
        """Apply a UI decision only if the prepared revision is still current."""
        preparation = prepared.preparation
        existing = preparation.existing
        candidate = preparation.candidate
        policy = prepared.policy
        if prepared.decision_required:
            resolved_decision = decision or DuplicateDecision(
                policy="keep_existing",
                apply_for_session=False,
            )
            policy = resolved_decision.policy
            if resolved_decision.apply_for_session:
                self._session_policy = resolved_decision.policy

        if existing is None or policy is None:
            action = "create"
            resolved = candidate
        elif policy == "keep_existing":
            action = "skip"
            resolved = existing
        else:
            resolved = apply_policy(existing, candidate, policy)
            action = "append_new" if policy == "add_as_new" else "overwrite"

        write_outcome = self._workbook.commit_prepared(
            preparation,
            action,
            resolved,
            list(self._policy.excel_columns),
            backup_on_overwrite=True,
        )
        written_entry = write_outcome.entry

        # Map (action, policy) → SaveOutcome.status.
        if action == "create":
            status = "saved"
        elif action == "append_new":
            status = "appended_new"
        elif action == "skip":
            status = "kept"
        else:  # action == "overwrite"
            status = "merged" if policy == "merge_examples_and_memo" else "updated"
        return SaveOutcome(
            status=status,
            path=preparation.path,
            entry=written_entry,
            backup_path=write_outcome.backup_path,
            entry_ref=write_outcome.entry_ref,
            revision=write_outcome.revision,
        )
