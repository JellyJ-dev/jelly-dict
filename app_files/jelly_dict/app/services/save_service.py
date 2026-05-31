"""Excel save flow including duplicate handling."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.duplicate_checker import (
    DuplicateDecision,
    DuplicatePolicy,
    apply_policy,
    is_duplicate,
)
from app.core.models import VocabularyEntry
from app.storage import excel_writer
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)

DuplicatePrompt = Callable[[VocabularyEntry, VocabularyEntry], DuplicateDecision]


@dataclass
class SaveOutcome:
    status: str  # "saved" | "updated" | "merged" | "kept" | "appended_new"
    path: Path
    entry: VocabularyEntry
    backup_path: Path | None = None


class SaveService:
    def __init__(
        self,
        settings: Settings,
        duplicate_prompt: DuplicatePrompt | None = None,
    ) -> None:
        self._settings = settings
        self._prompt = duplicate_prompt
        self._session_policy: DuplicatePolicy | None = None

    def excel_path_for(self, language: str) -> Path:
        return Path(self._settings.excel_path_for(language)).expanduser()

    def reset_session_policy(self) -> None:
        self._session_policy = None

    def save(self, entry: VocabularyEntry) -> SaveOutcome:
        """Persist `entry` to the language-specific Excel file with a
        single workbook load. The resolver returns an explicit action
        derived from the duplicate policy so the writer can stay simple."""
        path = self.excel_path_for(entry.language)
        path.parent.mkdir(parents=True, exist_ok=True)

        policy_holder: dict[str, DuplicatePolicy | None] = {"policy": None}

        def resolver(existing, candidate):
            if not is_duplicate(existing, candidate):
                policy_holder["policy"] = None
                return "create", candidate
            policy = self._resolve_policy(existing, candidate)
            policy_holder["policy"] = policy
            if policy == "keep_existing":
                return "skip", existing
            resolved = apply_policy(existing, candidate, policy)
            if policy == "add_as_new":
                return "append_new", resolved
            return "overwrite", resolved

        write_outcome = excel_writer.save_with_resolver(
            path,
            entry,
            self._settings.excel_columns,
            resolver,
            backup_on_overwrite=True,
        )
        action, written_entry = write_outcome

        # Map (action, policy) → SaveOutcome.status.
        policy = policy_holder["policy"]
        if action == "create":
            status = "saved"
        elif action == "append_new":
            status = "appended_new"
        elif action == "skip":
            status = "kept"
        else:  # action == "overwrite"
            status = (
                "merged" if policy == "merge_examples_and_memo" else "updated"
            )
        return SaveOutcome(
            status=status,
            path=path,
            entry=written_entry,
            backup_path=write_outcome.backup_path,
        )

    def _resolve_policy(
        self,
        existing: VocabularyEntry,
        candidate: VocabularyEntry,
    ) -> DuplicatePolicy:
        if self._session_policy is not None:
            return self._session_policy

        configured = self._settings.duplicate_policy
        if configured != "ask" or self._prompt is None:
            if configured == "ask":
                # No prompt available (headless context): default to update.
                return "update_existing"
            return configured  # type: ignore[return-value]

        decision = self._prompt(existing, candidate)
        if decision.apply_for_session:
            self._session_policy = decision.policy
        return decision.policy
