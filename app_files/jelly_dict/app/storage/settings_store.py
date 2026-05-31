from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import config

EXCEL_COLUMN_KEYS_DEFAULT = [
    "language",
    "word",
    "reading",
    "part_of_speech",
    "meanings_summary",
    "meanings_detail",
    "examples",
    "example_translations",
    "synonyms",
    "antonyms",
    "tags",
    "memo",
    "source_url",
    "created_at",
    "updated_at",
]


@dataclass
class Settings:
    default_excel_dir: str = ""
    # Per-language target Excel files. Empty string -> auto path under default_excel_dir.
    excel_path_en: str = ""
    excel_path_ja: str = ""
    # Per-language Anki export targets.
    anki_path_en: str = ""
    anki_path_ja: str = ""
    default_anki_export_dir: str = ""
    request_delay_seconds: float = 1.0  # conservative: ~human typing speed
    cache_enabled: bool = True
    duplicate_policy: str = "ask"  # ask|keep_existing|update_existing|merge_examples_and_memo|add_as_new
    excel_columns: list[str] = field(default_factory=lambda: list(EXCEL_COLUMN_KEYS_DEFAULT))
    theme: str = "dark"
    show_preview: bool = False  # default OFF for speed; toggle on to edit details
    default_deck_name: str = "JellyDict"
    language_label_translate: bool = True
    provider: str = "naver_crawler"  # future: naver_api, etc.
    ocr_provider: str = "apple_vision"
    # AnkiConnect (localhost RPC to the Anki desktop addon).
    ankiconnect_enabled: bool = False
    ankiconnect_url: str = "http://127.0.0.1:8765"
    ankiconnect_deck_prefix: str = "JellyDict"

    # OCR — Google Cloud Vision endpoint. The API key is stored in the OS
    # keychain via app.storage.secret_store, never in this file.
    google_vision_endpoint: str = "https://vision.googleapis.com/v1/images:annotate"

    # Anki TTS / audio — default OFF so existing export output is unchanged.
    tts_enabled: bool = False
    tts_play_front: bool = True
    tts_play_back: bool = True
    tts_play_examples: bool = False
    tts_engine_en: str = "kokoro"          # kokoro | edge | none
    tts_engine_ja: str = "kokoro"          # kokoro | voicevox | edge | none
    tts_voice_en: str = "af_heart"
    tts_voice_ja: str = "jf_alpha"
    tts_bitrate: str = "96k"
    tts_sample_rate: int = 44100
    voicevox_url: str = "http://127.0.0.1:50021"
    # User-curated VOICEVOX voice list. Defaults to the 5 standard
    # (ノーマル-style) voices; the settings UI lets the user add more.
    tts_voicevox_voices: list[str] = field(default_factory=lambda: [
        "3:ずんだもん (ノーマル)",
        "2:四国めたん (ノーマル)",
        "8:春日部つむぎ (ノーマル)",
        "13:青山龍星 (ノーマル)",
        "16:九州そら (ノーマル)",
    ])

    # Anki export UX — keep normal exports one-click while allowing smart
    # checks when audio state changes or an engine looks unavailable.
    anki_export_confirm_mode: str = "smart"  # smart | always | never
    last_apkg_export_tts_enabled: bool | None = None
    last_apkg_export_audio_policy: str = "settings"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def excel_path_for(self, language: str) -> str:
        from pathlib import Path

        explicit = self.excel_path_ja if language == "ja" else self.excel_path_en
        if explicit:
            return explicit
        base = Path(self.default_excel_dir or str(config.default_excel_dir()))
        name = "vocab_ja.xlsx" if language == "ja" else "vocab_en.xlsx"
        return str(base / name)

    def anki_path_for(self, language: str) -> str:
        from pathlib import Path

        explicit = self.anki_path_ja if language == "ja" else self.anki_path_en
        if explicit:
            return explicit
        base = Path(self.default_anki_export_dir or str(config.default_excel_dir()))
        name = "jelly-dict_ja.apkg" if language == "ja" else "jelly-dict_en.apkg"
        return str(base / name)


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
