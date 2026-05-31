from __future__ import annotations

from pathlib import Path

from app.core.duplicate_checker import DuplicateDecision
from app.core.models import VocabularyEntry
from app.services.save_service import SaveService
from app.storage.settings_store import EXCEL_COLUMN_KEYS_DEFAULT, Settings


def _settings(tmp_path: Path, policy: str = "ask") -> Settings:
    return Settings(
        default_excel_dir=str(tmp_path),
        excel_path_en=str(tmp_path / "vocab_en.xlsx"),
        excel_path_ja=str(tmp_path / "vocab_ja.xlsx"),
        default_anki_export_dir=str(tmp_path),
        request_delay_seconds=0.0,
        cache_enabled=False,
        duplicate_policy=policy,
        excel_columns=list(EXCEL_COLUMN_KEYS_DEFAULT),
    )


def test_first_save_creates_file_and_appends(tmp_path: Path):
    service = SaveService(_settings(tmp_path))
    outcome = service.save(VocabularyEntry(language="en", word="apple"))
    assert outcome.status == "saved"
    assert outcome.path.exists()
    assert outcome.backup_path is None


def test_duplicate_with_update_policy_replaces_row(tmp_path: Path):
    service = SaveService(_settings(tmp_path, policy="update_existing"))
    service.save(VocabularyEntry(language="en", word="apple", memo="v1"))
    outcome = service.save(VocabularyEntry(language="en", word="apple", memo="v2"))
    assert outcome.status == "updated"
    assert outcome.entry.memo == "v2"
    assert outcome.backup_path is not None
    assert outcome.backup_path.exists()

    from app.storage.excel_writer import list_entries

    backup_entries = list_entries(outcome.backup_path)
    assert len(backup_entries) == 1
    assert backup_entries[0].memo == "v1"


def test_duplicate_with_merge_policy_backs_up_original_row(tmp_path: Path):
    service = SaveService(_settings(tmp_path, policy="merge_examples_and_memo"))
    service.save(VocabularyEntry(language="en", word="apple", memo="v1"))
    outcome = service.save(VocabularyEntry(language="en", word="apple", memo="v2"))
    assert outcome.status == "merged"
    assert outcome.entry.memo == "v1\n---\nv2"
    assert outcome.backup_path is not None
    assert outcome.backup_path.exists()

    from app.storage.excel_writer import list_entries

    backup_entries = list_entries(outcome.backup_path)
    assert len(backup_entries) == 1
    assert backup_entries[0].memo == "v1"


def test_duplicate_with_keep_existing_skips(tmp_path: Path):
    service = SaveService(_settings(tmp_path, policy="keep_existing"))
    service.save(VocabularyEntry(language="en", word="apple", memo="v1"))
    outcome = service.save(VocabularyEntry(language="en", word="apple", memo="v2"))
    assert outcome.status == "kept"
    assert outcome.entry.memo == "v1"
    assert outcome.backup_path is None


def test_duplicate_prompt_invoked(tmp_path: Path):
    service = SaveService(
        _settings(tmp_path),
        duplicate_prompt=lambda existing, candidate: DuplicateDecision(
            policy="update_existing", apply_for_session=False
        ),
    )
    service.save(VocabularyEntry(language="en", word="apple", memo="v1"))
    outcome = service.save(VocabularyEntry(language="en", word="apple", memo="v2"))
    assert outcome.status == "updated"


def test_session_policy_persists_until_reset(tmp_path: Path):
    calls = {"count": 0}

    def prompt(existing, candidate):
        calls["count"] += 1
        return DuplicateDecision(policy="keep_existing", apply_for_session=True)

    service = SaveService(_settings(tmp_path), duplicate_prompt=prompt)
    service.save(VocabularyEntry(language="en", word="apple", memo="v1"))
    service.save(VocabularyEntry(language="en", word="apple", memo="v2"))
    service.save(VocabularyEntry(language="en", word="apple", memo="v3"))
    assert calls["count"] == 1
