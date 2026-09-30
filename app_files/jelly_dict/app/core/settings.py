from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

from app.core import config
from app.core.url_safety import (
    require_google_vision_endpoint,
    require_loopback_http_url,
)

CURRENT_SETTINGS_SCHEMA_VERSION = 1

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
EXCEL_COLUMN_KEYS = frozenset(EXCEL_COLUMN_KEYS_DEFAULT)

DICTIONARY_PROVIDER_IDS = frozenset({"naver_crawler", "manual"})
OCR_PROVIDER_IDS = frozenset({"apple_vision", "google_vision"})
TTS_PROVIDER_IDS = frozenset({"none", "kokoro", "voicevox", "edge"})
DUPLICATE_POLICIES = frozenset(
    {
        "ask",
        "keep_existing",
        "update_existing",
        "merge_examples_and_memo",
        "add_as_new",
    }
)
ANKI_EXPORT_CONFIRM_MODES = frozenset({"smart", "always", "never"})
APKG_AUDIO_POLICIES = frozenset({"settings", "force_tts", "no_tts", "remove_audio"})


class SettingsValidationError(ValueError):
    """An edit buffer contains values that cannot become runtime settings."""

    def __init__(self, errors: Mapping[str, str]) -> None:
        self.errors = dict(errors)
        detail = "; ".join(f"{key}: {message}" for key, message in errors.items())
        super().__init__(detail or "invalid settings")


@dataclass(frozen=True)
class PathSettings:
    default_excel_dir: str = ""
    excel_path_en: str = ""
    excel_path_ja: str = ""
    anki_path_en: str = ""
    anki_path_ja: str = ""
    default_anki_export_dir: str = ""

    def excel_path_for(self, language: str) -> str:
        explicit = self.excel_path_ja if language == "ja" else self.excel_path_en
        if explicit:
            return explicit
        base = Path(self.default_excel_dir or str(config.default_excel_dir()))
        name = "vocab_ja.xlsx" if language == "ja" else "vocab_en.xlsx"
        return str(base / name)

    def anki_path_for(self, language: str) -> str:
        explicit = self.anki_path_ja if language == "ja" else self.anki_path_en
        if explicit:
            return explicit
        base = Path(self.default_anki_export_dir or str(config.default_excel_dir()))
        name = "jelly-dict_ja.apkg" if language == "ja" else "jelly-dict_en.apkg"
        return str(base / name)


@dataclass(frozen=True)
class LookupSettings:
    request_delay_seconds: float = 1.0
    cache_enabled: bool = True
    duplicate_policy: str = "ask"
    excel_columns: tuple[str, ...] = tuple(EXCEL_COLUMN_KEYS_DEFAULT)
    provider: str = "naver_crawler"


@dataclass(frozen=True)
class UiPreferences:
    theme: str = "dark"
    show_preview: bool = False
    default_deck_name: str = "JellyDict"
    language_label_translate: bool = True


@dataclass(frozen=True)
class OcrSettings:
    ocr_provider: str = "apple_vision"
    google_vision_endpoint: str = "https://vision.googleapis.com/v1/images:annotate"


@dataclass(frozen=True)
class AnkiSettings:
    ankiconnect_enabled: bool = False
    ankiconnect_url: str = "http://127.0.0.1:8765"
    ankiconnect_deck_prefix: str = "JellyDict"
    anki_export_confirm_mode: str = "smart"
    last_apkg_export_tts_enabled: bool | None = None
    last_apkg_export_audio_policy: str = "settings"


@dataclass(frozen=True)
class TtsSettings:
    tts_enabled: bool = False
    tts_play_front: bool = True
    tts_play_back: bool = True
    tts_play_examples: bool = False
    tts_pre_generate_on_save: bool = False
    tts_engine_en: str = "kokoro"
    tts_engine_ja: str = "kokoro"
    tts_voice_en: str = "af_heart"
    tts_voice_ja: str = "jf_alpha"
    tts_bitrate: str = "96k"
    tts_sample_rate: int = 44100
    voicevox_url: str = "http://127.0.0.1:50021"
    tts_voicevox_voices: tuple[str, ...] = (
        "3:ずんだもん (ノーマル)",
        "2:四国めたん (ノーマル)",
        "8:春日部つむぎ (ノーマル)",
        "13:青山龍星 (ノーマル)",
        "16:九州そら (ノーマル)",
    )


@dataclass(frozen=True)
class TtsRuntimeSettings:
    """Only the path and TTS groups needed by synthesis/export adapters."""

    paths: PathSettings
    tts: TtsSettings

    def excel_path_for(self, language: str) -> str:
        return self.paths.excel_path_for(language)

    def to_dict(self) -> dict[str, Any]:
        draft = SettingsDraft()
        for name in _TTS_FIELD_NAMES:
            setattr(draft, name, deepcopy(getattr(self.tts, name)))
        draft.default_excel_dir = self.paths.default_excel_dir
        draft.excel_path_en = self.paths.excel_path_en
        draft.excel_path_ja = self.paths.excel_path_ja
        return draft.to_dict()

    def __getattr__(self, name: str) -> Any:
        if name in _TTS_FIELD_NAMES:
            return getattr(self.tts, name)
        raise AttributeError(name)


@dataclass(frozen=True)
class AppSettings:
    """Immutable runtime settings, composed by responsibility.

    Flat read properties and ``to_dict`` are a compatibility bridge for
    adapters while application services migrate to the narrower group values.
    The persisted JSON intentionally remains flat.
    """

    paths: PathSettings = field(default_factory=PathSettings)
    lookup: LookupSettings = field(default_factory=LookupSettings)
    ui: UiPreferences = field(default_factory=UiPreferences)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    anki: AnkiSettings = field(default_factory=AnkiSettings)
    tts: TtsSettings = field(default_factory=TtsSettings)
    schema_version: int = CURRENT_SETTINGS_SCHEMA_VERSION
    _unknown_json: str = field(default="{}", repr=False, compare=False)

    @classmethod
    def from_flat(
        cls,
        values: Mapping[str, Any] | SettingsDraft | AppSettings,
        *,
        unknown_fields: Mapping[str, Any] | None = None,
        validate: bool = True,
    ) -> AppSettings:
        if isinstance(values, cls):
            return values
        if isinstance(values, SettingsDraft):
            draft = SettingsDraft.from_mapping(values.to_dict())
            inherited_unknown = values.unknown_fields
        else:
            draft = SettingsDraft.from_mapping(values)
            inherited_unknown = {
                key: deepcopy(value)
                for key, value in values.items()
                if key not in FLAT_SETTINGS_KEYS
            }
        if validate:
            draft.validate()
        unknown = dict(inherited_unknown)
        if unknown_fields is not None:
            unknown = deepcopy(dict(unknown_fields))
        return cls(
            paths=PathSettings(
                default_excel_dir=draft.default_excel_dir,
                excel_path_en=draft.excel_path_en,
                excel_path_ja=draft.excel_path_ja,
                anki_path_en=draft.anki_path_en,
                anki_path_ja=draft.anki_path_ja,
                default_anki_export_dir=draft.default_anki_export_dir,
            ),
            lookup=LookupSettings(
                request_delay_seconds=float(draft.request_delay_seconds),
                cache_enabled=draft.cache_enabled,
                duplicate_policy=draft.duplicate_policy,
                excel_columns=tuple(draft.excel_columns),
                provider=draft.provider,
            ),
            ui=UiPreferences(
                theme=draft.theme,
                show_preview=draft.show_preview,
                default_deck_name=draft.default_deck_name,
                language_label_translate=draft.language_label_translate,
            ),
            ocr=OcrSettings(
                ocr_provider=draft.ocr_provider,
                google_vision_endpoint=draft.google_vision_endpoint,
            ),
            anki=AnkiSettings(
                ankiconnect_enabled=draft.ankiconnect_enabled,
                ankiconnect_url=draft.ankiconnect_url,
                ankiconnect_deck_prefix=draft.ankiconnect_deck_prefix,
                anki_export_confirm_mode=draft.anki_export_confirm_mode,
                last_apkg_export_tts_enabled=draft.last_apkg_export_tts_enabled,
                last_apkg_export_audio_policy=draft.last_apkg_export_audio_policy,
            ),
            tts=TtsSettings(
                tts_enabled=draft.tts_enabled,
                tts_play_front=draft.tts_play_front,
                tts_play_back=draft.tts_play_back,
                tts_play_examples=draft.tts_play_examples,
                tts_pre_generate_on_save=draft.tts_pre_generate_on_save,
                tts_engine_en=draft.tts_engine_en,
                tts_engine_ja=draft.tts_engine_ja,
                tts_voice_en=draft.tts_voice_en,
                tts_voice_ja=draft.tts_voice_ja,
                tts_bitrate=draft.tts_bitrate,
                tts_sample_rate=draft.tts_sample_rate,
                voicevox_url=draft.voicevox_url,
                tts_voicevox_voices=tuple(draft.tts_voicevox_voices),
            ),
            schema_version=draft.schema_version,
            _unknown_json=_encode_unknown(unknown),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "default_excel_dir": self.paths.default_excel_dir,
            "excel_path_en": self.paths.excel_path_en,
            "excel_path_ja": self.paths.excel_path_ja,
            "anki_path_en": self.paths.anki_path_en,
            "anki_path_ja": self.paths.anki_path_ja,
            "default_anki_export_dir": self.paths.default_anki_export_dir,
            "request_delay_seconds": self.lookup.request_delay_seconds,
            "cache_enabled": self.lookup.cache_enabled,
            "duplicate_policy": self.lookup.duplicate_policy,
            "excel_columns": list(self.lookup.excel_columns),
            "theme": self.ui.theme,
            "show_preview": self.ui.show_preview,
            "default_deck_name": self.ui.default_deck_name,
            "language_label_translate": self.ui.language_label_translate,
            "provider": self.lookup.provider,
            "ocr_provider": self.ocr.ocr_provider,
            "ankiconnect_enabled": self.anki.ankiconnect_enabled,
            "ankiconnect_url": self.anki.ankiconnect_url,
            "ankiconnect_deck_prefix": self.anki.ankiconnect_deck_prefix,
            "google_vision_endpoint": self.ocr.google_vision_endpoint,
            "tts_enabled": self.tts.tts_enabled,
            "tts_play_front": self.tts.tts_play_front,
            "tts_play_back": self.tts.tts_play_back,
            "tts_play_examples": self.tts.tts_play_examples,
            "tts_pre_generate_on_save": self.tts.tts_pre_generate_on_save,
            "tts_engine_en": self.tts.tts_engine_en,
            "tts_engine_ja": self.tts.tts_engine_ja,
            "tts_voice_en": self.tts.tts_voice_en,
            "tts_voice_ja": self.tts.tts_voice_ja,
            "tts_bitrate": self.tts.tts_bitrate,
            "tts_sample_rate": self.tts.tts_sample_rate,
            "voicevox_url": self.tts.voicevox_url,
            "tts_voicevox_voices": list(self.tts.tts_voicevox_voices),
            "anki_export_confirm_mode": self.anki.anki_export_confirm_mode,
            "last_apkg_export_tts_enabled": self.anki.last_apkg_export_tts_enabled,
            "last_apkg_export_audio_policy": self.anki.last_apkg_export_audio_policy,
        }

    def to_storage_dict(self) -> dict[str, Any]:
        payload = self.unknown_fields
        payload.update(self.to_dict())
        return payload

    @property
    def unknown_fields(self) -> dict[str, Any]:
        value = json.loads(self._unknown_json)
        return value if isinstance(value, dict) else {}

    def draft(self) -> SettingsDraft:
        return SettingsDraft.from_snapshot(self)

    def tts_runtime(self) -> TtsRuntimeSettings:
        return TtsRuntimeSettings(self.paths, self.tts)

    def with_changes(self, **changes: Any) -> AppSettings:
        draft = self.draft()
        for key, value in changes.items():
            if key not in FLAT_SETTINGS_KEYS or key == "schema_version":
                raise KeyError(f"unknown settings key: {key}")
            setattr(draft, key, deepcopy(value))
        return draft.snapshot()

    def excel_path_for(self, language: str) -> str:
        return self.paths.excel_path_for(language)

    def anki_path_for(self, language: str) -> str:
        return self.paths.anki_path_for(language)

    def __getattr__(self, name: str) -> Any:
        route = _FLAT_PROPERTY_ROUTES.get(name)
        if route is None:
            raise AttributeError(name)
        group_name, attribute = route
        return getattr(object.__getattribute__(self, group_name), attribute)


@dataclass
class SettingsDraft:
    """Mutable flat buffer used only while editing or decoding settings."""

    schema_version: int = CURRENT_SETTINGS_SCHEMA_VERSION
    default_excel_dir: str = ""
    excel_path_en: str = ""
    excel_path_ja: str = ""
    anki_path_en: str = ""
    anki_path_ja: str = ""
    default_anki_export_dir: str = ""
    request_delay_seconds: float = 1.0
    cache_enabled: bool = True
    duplicate_policy: str = "ask"
    excel_columns: list[str] = field(default_factory=lambda: list(EXCEL_COLUMN_KEYS_DEFAULT))
    theme: str = "dark"
    show_preview: bool = False
    default_deck_name: str = "JellyDict"
    language_label_translate: bool = True
    provider: str = "naver_crawler"
    ocr_provider: str = "apple_vision"
    ankiconnect_enabled: bool = False
    ankiconnect_url: str = "http://127.0.0.1:8765"
    ankiconnect_deck_prefix: str = "JellyDict"
    google_vision_endpoint: str = "https://vision.googleapis.com/v1/images:annotate"
    tts_enabled: bool = False
    tts_play_front: bool = True
    tts_play_back: bool = True
    tts_play_examples: bool = False
    tts_pre_generate_on_save: bool = False
    tts_engine_en: str = "kokoro"
    tts_engine_ja: str = "kokoro"
    tts_voice_en: str = "af_heart"
    tts_voice_ja: str = "jf_alpha"
    tts_bitrate: str = "96k"
    tts_sample_rate: int = 44100
    voicevox_url: str = "http://127.0.0.1:50021"
    tts_voicevox_voices: list[str] = field(
        default_factory=lambda: list(TtsSettings().tts_voicevox_voices)
    )
    anki_export_confirm_mode: str = "smart"
    last_apkg_export_tts_enabled: bool | None = None
    last_apkg_export_audio_policy: str = "settings"
    _unknown_fields: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SettingsDraft:
        known = {item.name for item in fields(cls) if not item.name.startswith("_")}
        draft = cls(**{key: deepcopy(value) for key, value in values.items() if key in known})
        draft._unknown_fields = {
            key: deepcopy(value) for key, value in values.items() if key not in known
        }
        return draft

    @classmethod
    def from_snapshot(cls, settings: AppSettings) -> SettingsDraft:
        draft = cls.from_mapping(settings.to_dict())
        draft._unknown_fields = settings.unknown_fields
        return draft

    def to_dict(self) -> dict[str, Any]:
        return {
            item.name: deepcopy(getattr(self, item.name))
            for item in fields(self)
            if not item.name.startswith("_")
        }

    @property
    def unknown_fields(self) -> dict[str, Any]:
        return deepcopy(self._unknown_fields)

    def validate(self) -> None:
        errors = settings_validation_errors(self)
        if errors:
            raise SettingsValidationError(errors)

    def snapshot(self) -> AppSettings:
        return AppSettings.from_flat(self, unknown_fields=self._unknown_fields)

    def excel_path_for(self, language: str) -> str:
        return _paths_from_draft(self).excel_path_for(language)

    def anki_path_for(self, language: str) -> str:
        return _paths_from_draft(self).anki_path_for(language)


class Settings(SettingsDraft):
    """Compatibility constructor; runtime code should use ``AppSettings``."""


# Old import names remain as draft aliases until downstream plugins migrate.
FileTargetSettings = SettingsDraft
SaveBehaviorSettings = SettingsDraft
UiPreferenceSettings = SettingsDraft
ProviderSettings = SettingsDraft
ExportPreferenceSettings = SettingsDraft


def settings_snapshot(
    value: AppSettings | SettingsDraft,
    *,
    validate: bool = True,
) -> AppSettings:
    if isinstance(value, AppSettings):
        return value
    return AppSettings.from_flat(
        value,
        unknown_fields=value.unknown_fields,
        validate=validate,
    )


def settings_validation_errors(settings: SettingsDraft) -> dict[str, str]:
    errors: dict[str, str] = {}
    delay = settings.request_delay_seconds
    if (
        isinstance(delay, bool)
        or not isinstance(delay, (int, float))
        or not math.isfinite(float(delay))
        or not 0.3 <= float(delay) <= 60.0
    ):
        errors["request_delay_seconds"] = "0.3~60 사이의 유한한 숫자여야 합니다"

    sample_rate = settings.tts_sample_rate
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or not 8000 <= sample_rate <= 192000
    ):
        errors["tts_sample_rate"] = "8000~192000 사이의 정수여야 합니다"

    match = re.fullmatch(r"([1-9][0-9]{0,3})k", settings.tts_bitrate or "")
    if match is None or not 8 <= int(match.group(1)) <= 512:
        errors["tts_bitrate"] = "8k~512k 형식이어야 합니다"

    for key, label in (
        ("ankiconnect_url", "AnkiConnect"),
        ("voicevox_url", "VOICEVOX"),
    ):
        try:
            require_loopback_http_url(getattr(settings, key), label)
        except ValueError as exc:
            errors[key] = str(exc)
    try:
        require_google_vision_endpoint(settings.google_vision_endpoint)
    except ValueError as exc:
        errors["google_vision_endpoint"] = str(exc)

    if settings.provider not in DICTIONARY_PROVIDER_IDS:
        errors["provider"] = "지원하지 않는 사전 provider입니다"
    if settings.ocr_provider not in OCR_PROVIDER_IDS:
        errors["ocr_provider"] = "지원하지 않는 OCR provider입니다"
    for key in ("tts_engine_en", "tts_engine_ja"):
        if getattr(settings, key) not in TTS_PROVIDER_IDS:
            errors[key] = "지원하지 않는 TTS provider입니다"
    if settings.duplicate_policy not in DUPLICATE_POLICIES:
        errors["duplicate_policy"] = "지원하지 않는 중복 처리 정책입니다"
    if settings.anki_export_confirm_mode not in ANKI_EXPORT_CONFIRM_MODES:
        errors["anki_export_confirm_mode"] = "지원하지 않는 확인 정책입니다"
    if settings.last_apkg_export_audio_policy not in APKG_AUDIO_POLICIES:
        errors["last_apkg_export_audio_policy"] = "지원하지 않는 오디오 정책입니다"

    columns = settings.excel_columns
    if not isinstance(columns, list) or not columns:
        errors["excel_columns"] = "하나 이상의 열 키가 필요합니다"
    elif (
        any(not isinstance(key, str) or key not in EXCEL_COLUMN_KEYS for key in columns)
        or len(columns) != len(set(columns))
        or "word" not in columns
    ):
        errors["excel_columns"] = "알 수 없는 키·중복 키가 없어야 하며 word가 필요합니다"
    return errors


def validation_error_for_key(
    key: str,
    value: Any,
    defaults: SettingsDraft,
) -> str | None:
    candidate = SettingsDraft.from_mapping(defaults.to_dict())
    setattr(candidate, key, deepcopy(value))
    return settings_validation_errors(candidate).get(key)


def _paths_from_draft(settings: SettingsDraft) -> PathSettings:
    return PathSettings(
        default_excel_dir=settings.default_excel_dir,
        excel_path_en=settings.excel_path_en,
        excel_path_ja=settings.excel_path_ja,
        anki_path_en=settings.anki_path_en,
        anki_path_ja=settings.anki_path_ja,
        default_anki_export_dir=settings.default_anki_export_dir,
    )


def _encode_unknown(values: Mapping[str, Any]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_FLAT_PROPERTY_ROUTES: dict[str, tuple[str, str]] = {
    **{
        name: ("paths", name)
        for name in (
            "default_excel_dir",
            "excel_path_en",
            "excel_path_ja",
            "anki_path_en",
            "anki_path_ja",
            "default_anki_export_dir",
        )
    },
    **{
        name: ("lookup", name)
        for name in (
            "request_delay_seconds",
            "cache_enabled",
            "duplicate_policy",
            "excel_columns",
            "provider",
        )
    },
    **{
        name: ("ui", name)
        for name in (
            "theme",
            "show_preview",
            "default_deck_name",
            "language_label_translate",
        )
    },
    **{
        name: ("ocr", name)
        for name in (
            "ocr_provider",
            "google_vision_endpoint",
        )
    },
    **{
        name: ("anki", name)
        for name in (
            "ankiconnect_enabled",
            "ankiconnect_url",
            "ankiconnect_deck_prefix",
            "anki_export_confirm_mode",
            "last_apkg_export_tts_enabled",
            "last_apkg_export_audio_policy",
        )
    },
    **{
        name: ("tts", name)
        for name in (
            "tts_enabled",
            "tts_play_front",
            "tts_play_back",
            "tts_play_examples",
            "tts_pre_generate_on_save",
            "tts_engine_en",
            "tts_engine_ja",
            "tts_voice_en",
            "tts_voice_ja",
            "tts_bitrate",
            "tts_sample_rate",
            "voicevox_url",
            "tts_voicevox_voices",
        )
    },
}

_TTS_FIELD_NAMES = frozenset(
    name for name, route in _FLAT_PROPERTY_ROUTES.items() if route[0] == "tts"
)

FLAT_SETTINGS_KEYS = frozenset(
    item.name for item in fields(SettingsDraft) if not item.name.startswith("_")
)

__all__ = [
    "AppSettings",
    "AnkiSettings",
    "CURRENT_SETTINGS_SCHEMA_VERSION",
    "EXCEL_COLUMN_KEYS",
    "EXCEL_COLUMN_KEYS_DEFAULT",
    "ExportPreferenceSettings",
    "FileTargetSettings",
    "FLAT_SETTINGS_KEYS",
    "LookupSettings",
    "OcrSettings",
    "PathSettings",
    "ProviderSettings",
    "SaveBehaviorSettings",
    "Settings",
    "SettingsDraft",
    "SettingsValidationError",
    "TtsSettings",
    "TtsRuntimeSettings",
    "UiPreferenceSettings",
    "UiPreferences",
    "settings_snapshot",
    "validation_error_for_key",
]
