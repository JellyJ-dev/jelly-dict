from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import config
from app.storage.settings_models import EXCEL_COLUMN_KEYS_DEFAULT, Settings


def _defaults() -> Settings:
    s = Settings()
    s.default_excel_dir = str(config.default_excel_dir())
    s.default_anki_export_dir = str(config.default_excel_dir())
    return s


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.settings_path()
        self._cache: Settings | None = None

    def load(self) -> Settings:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = _defaults()
            self.save(self._cache)
            return self._cache
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt settings: rebuild from defaults rather than crash.
            self._backup_corrupt_settings()
            self._cache = _defaults()
            self.save(self._cache)
            return self._cache
        merged = _defaults()
        valid_keys = {f.name for f in fields(Settings)}
        for key, value in raw.items():
            if key in valid_keys:
                setattr(merged, key, _coerce_setting_value(key, value, getattr(merged, key)))
        self._cache = merged
        return merged

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n"
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
        self._cache = settings

    def update(self, **changes: Any) -> Settings:
        current = self.load()
        for key, value in changes.items():
            if hasattr(current, key):
                setattr(current, key, value)
        self.save(current)
        return current

    def _backup_corrupt_settings(self) -> Path | None:
        if not self.path.exists():
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.path.with_name(
            f"{self.path.name}.corrupt.{timestamp}.bak"
        )
        try:
            shutil.copy2(self.path, backup_path)
        except OSError:
            return None
        return backup_path


_ALLOWED_VALUES = {
    "duplicate_policy": {
        "ask",
        "keep_existing",
        "update_existing",
        "merge_examples_and_memo",
        "add_as_new",
    },
    "provider": {"naver_crawler"},
    "ocr_provider": {"apple_vision", "google_vision"},
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
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return value
        return default
    if default is None:
        return value if value is None or isinstance(value, bool) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return value
