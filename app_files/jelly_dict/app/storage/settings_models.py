from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
class FileTargetSettings:
    default_excel_dir: str = ""
    excel_path_en: str = ""
    excel_path_ja: str = ""
    anki_path_en: str = ""
    anki_path_ja: str = ""
    default_anki_export_dir: str = ""


@dataclass
class SaveBehaviorSettings(FileTargetSettings):
    request_delay_seconds: float = 1.0
    cache_enabled: bool = True
    duplicate_policy: str = "ask"
    excel_columns: list[str] = field(default_factory=lambda: list(EXCEL_COLUMN_KEYS_DEFAULT))


@dataclass
class UiPreferenceSettings(SaveBehaviorSettings):
    theme: str = "dark"
    show_preview: bool = False
    default_deck_name: str = "JellyDict"
    language_label_translate: bool = True


@dataclass
class ProviderSettings(UiPreferenceSettings):
    provider: str = "naver_crawler"
    ocr_provider: str = "apple_vision"
    ankiconnect_enabled: bool = False
    ankiconnect_url: str = "http://127.0.0.1:8765"
    ankiconnect_deck_prefix: str = "JellyDict"
    google_vision_endpoint: str = "https://vision.googleapis.com/v1/images:annotate"


@dataclass
class TtsSettings(ProviderSettings):
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
    tts_voicevox_voices: list[str] = field(default_factory=lambda: [
        "3:ずんだもん (ノーマル)",
        "2:四国めたん (ノーマル)",
        "8:春日部つむぎ (ノーマル)",
        "13:青山龍星 (ノーマル)",
        "16:九州そら (ノーマル)",
    ])


@dataclass
class ExportPreferenceSettings(TtsSettings):
    anki_export_confirm_mode: str = "smart"
    last_apkg_export_tts_enabled: bool | None = None
    last_apkg_export_audio_policy: str = "settings"


@dataclass
class Settings(ExportPreferenceSettings):
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

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
