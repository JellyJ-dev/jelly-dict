from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import config
from app.core.settings import (
    CURRENT_SETTINGS_SCHEMA_VERSION,
    EXCEL_COLUMN_KEYS_DEFAULT,
    FLAT_SETTINGS_KEYS,
    AppSettings,
    Settings,
    SettingsDraft,
    settings_snapshot,
    validation_error_for_key,
)

log = logging.getLogger(__name__)


def _default_draft() -> SettingsDraft:
    draft = SettingsDraft()
    draft.default_excel_dir = str(config.default_excel_dir())
    draft.default_anki_export_dir = str(config.default_excel_dir())
    return draft


def _defaults() -> AppSettings:
    return _default_draft().snapshot()


class SettingsStore:
    """Atomic flat-JSON persistence for immutable runtime settings.

    Unknown keys are preserved verbatim and logged. Known keys are validated
    and normalized independently, so one damaged value cannot discard the
    rest of a user's settings.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.settings_path()
        self._cache: AppSettings | None = None
        self._lock = threading.RLock()

    def load(self) -> AppSettings:
        with self._lock:
            if self._cache is not None:
                return self._cache
            if not self.path.exists():
                snapshot = _defaults()
                self._write_snapshot(snapshot)
                self._cache = snapshot
                return snapshot
            try:
                raw_value = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw_value, dict):
                    raise ValueError("settings root must be a JSON object")
            except (json.JSONDecodeError, OSError, ValueError):
                self._backup_corrupt_settings()
                snapshot = _defaults()
                self._write_snapshot(snapshot)
                self._cache = snapshot
                return snapshot

            raw, migrated = _migrate_payload(raw_value)
            defaults = _default_draft()
            draft = SettingsDraft.from_mapping(defaults.to_dict())
            normalized = False
            for key, value in raw.items():
                if key not in FLAT_SETTINGS_KEYS or key == "schema_version":
                    continue
                default = getattr(defaults, key)
                coerced = _coerce_setting_value(key, value, default)
                if validation_error_for_key(key, coerced, defaults) is not None:
                    log.warning("invalid setting reset to default: %s", key)
                    coerced = deepcopy(default)
                if coerced != value:
                    normalized = True
                setattr(draft, key, coerced)
            migrated_version = raw.get(
                "schema_version",
                CURRENT_SETTINGS_SCHEMA_VERSION,
            )
            draft.schema_version = (
                migrated_version
                if isinstance(migrated_version, int)
                and migrated_version > CURRENT_SETTINGS_SCHEMA_VERSION
                else CURRENT_SETTINGS_SCHEMA_VERSION
            )

            unknown = {
                key: deepcopy(value) for key, value in raw.items() if key not in FLAT_SETTINGS_KEYS
            }
            if unknown:
                log.info(
                    "preserving unknown settings keys: %s",
                    ", ".join(sorted(unknown)),
                )
            snapshot = AppSettings.from_flat(draft, unknown_fields=unknown)
            if migrated or normalized:
                self._write_snapshot(snapshot)
            self._cache = snapshot
            return snapshot

    def save(self, settings: AppSettings | SettingsDraft) -> None:
        """Publish to memory only after validation and atomic disk commit."""
        with self._lock:
            snapshot = settings_snapshot(settings)
            self._write_snapshot(snapshot)
            self._cache = snapshot

    def update(self, **changes: Any) -> AppSettings:
        with self._lock:
            snapshot = self.load().with_changes(**changes)
            self._write_snapshot(snapshot)
            self._cache = snapshot
            return snapshot

    def _write_snapshot(self, snapshot: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                snapshot.to_storage_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                delete=False,
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                encoding="utf-8",
            ) as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_name = temp_file.name
            Path(temp_name).replace(self.path)
        finally:
            if temp_name:
                temp_path = Path(temp_name)
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

    def _backup_corrupt_settings(self) -> Path | None:
        if not self.path.exists():
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.path.with_name(f"{self.path.name}.corrupt.{timestamp}.bak")
        try:
            shutil.copy2(self.path, backup_path)
        except OSError:
            return None
        return backup_path


def _migrate_payload(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    payload = deepcopy(raw)
    raw_version = payload.get("schema_version", 0)
    version = raw_version if isinstance(raw_version, int) else 0
    if version > CURRENT_SETTINGS_SCHEMA_VERSION:
        log.warning(
            "settings schema %s is newer than supported schema %s; "
            "known keys loaded and unknown keys preserved",
            version,
            CURRENT_SETTINGS_SCHEMA_VERSION,
        )
        return payload, False
    migrated = version != CURRENT_SETTINGS_SCHEMA_VERSION
    if migrated:
        # Schema 0 was the same flat document without an explicit marker.
        log.info(
            "migrating settings schema %s -> %s",
            version,
            CURRENT_SETTINGS_SCHEMA_VERSION,
        )
        payload["schema_version"] = CURRENT_SETTINGS_SCHEMA_VERSION
    return payload, migrated


_ALLOWED_VALUES = {
    "duplicate_policy": {
        "ask",
        "keep_existing",
        "update_existing",
        "merge_examples_and_memo",
        "add_as_new",
    },
    "provider": {"naver_crawler", "manual"},
    "ocr_provider": {"apple_vision", "google_vision"},
    "tts_engine_en": {"none", "kokoro", "voicevox", "edge"},
    "tts_engine_ja": {"none", "kokoro", "voicevox", "edge"},
    "anki_export_confirm_mode": {"smart", "always", "never"},
    "last_apkg_export_audio_policy": {
        "settings",
        "force_tts",
        "no_tts",
        "remove_audio",
    },
}


def _coerce_setting_value(key: str, value: Any, default: Any) -> Any:
    if key in _ALLOWED_VALUES:
        return value if isinstance(value, str) and value in _ALLOWED_VALUES[key] else default
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return default
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, list):
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
        return deepcopy(default)
    if default is None:
        return value if value is None or isinstance(value, bool) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return deepcopy(value)


__all__ = [
    "AppSettings",
    "CURRENT_SETTINGS_SCHEMA_VERSION",
    "EXCEL_COLUMN_KEYS_DEFAULT",
    "Settings",
    "SettingsDraft",
    "SettingsStore",
]
