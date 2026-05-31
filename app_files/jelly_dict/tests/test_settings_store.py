from __future__ import annotations

import json

from app.storage.settings_store import EXCEL_COLUMN_KEYS_DEFAULT, SettingsStore


def test_creates_default_settings_on_first_load(isolated_runtime):
    store = SettingsStore()
    settings = store.load()
    assert settings.show_preview is False
    assert settings.duplicate_policy == "ask"
    assert settings.excel_columns == EXCEL_COLUMN_KEYS_DEFAULT
    assert settings.default_excel_dir.endswith("jelly-dict")
    assert settings.anki_export_confirm_mode == "smart"
    assert settings.last_apkg_export_tts_enabled is None


def test_persists_changes(isolated_runtime):
    store = SettingsStore()
    store.update(show_preview=False, request_delay_seconds=5.0)

    fresh = SettingsStore()
    settings = fresh.load()
    assert settings.show_preview is False
    assert settings.request_delay_seconds == 5.0


def test_corrupt_file_is_replaced_with_defaults(isolated_runtime):
    store = SettingsStore()
    store.path.write_text("not json", encoding="utf-8")
    settings = store.load()
    assert settings.show_preview is False
    # And the file is now valid JSON.
    json.loads(store.path.read_text(encoding="utf-8"))
    backups = list(store.path.parent.glob(f"{store.path.name}.corrupt.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "not json"


def test_unknown_keys_are_ignored(isolated_runtime):
    store = SettingsStore()
    store.path.write_text(
        json.dumps({"show_preview": False, "bogus_key": 123}),
        encoding="utf-8",
    )
    settings = store.load()
    assert settings.show_preview is False
    assert not hasattr(settings, "bogus_key")
