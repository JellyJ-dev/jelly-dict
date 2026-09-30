"""Explicit widget references for settings-dialog collaborators."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class SettingsUiRefs:
    tabs: Any
    excel_dir: Any
    excel_en: Any
    excel_ja: Any
    anki_dir: Any
    anki_en: Any
    anki_ja: Any
    deck_name: Any
    delay: Any
    cache_check: Any
    preview_check: Any
    dup_combo: Any
    provider_combo: Any
    ocr_combo: Any
    gv_key_edit: Any
    gv_key_save_btn: Any
    gv_key_clear_btn: Any
    gv_key_test_btn: Any
    gv_key_status: Any
    ankiconnect_check: Any
    ankiconnect_url: Any
    ankiconnect_test_btn: Any
    ankiconnect_status: Any
    tts_install_status: Any
    tts_install_btn: Any
    voicevox_install_btn: Any
    edge_install_btn: Any
    kokoro_uninstall_btn: Any
    voicevox_uninstall_btn: Any
    edge_uninstall_btn: Any
    tts_enabled_check: Any
    tts_play_front_check: Any
    tts_play_back_check: Any
    tts_play_examples_check: Any
    tts_pre_generate_check: Any
    tts_engine_en_combo: Any
    tts_voice_en_combo: Any
    tts_sample_en_btn: Any
    tts_engine_ja_combo: Any
    tts_voice_ja_combo: Any
    tts_voice_add_btn: Any
    tts_sample_ja_btn: Any
    tts_license_label: Any
    tts_clear_cache_btn: Any
    tts_cache_status: Any

    @classmethod
    def capture(cls, source: object) -> "SettingsUiRefs":
        return cls(**{field.name: getattr(source, field.name) for field in fields(cls)})

    def expose_legacy_facade(self, dialog: object) -> None:
        """Keep the existing SettingsDialog widget attributes source-compatible."""
        for field in fields(self):
            setattr(dialog, field.name, getattr(self, field.name))


__all__ = ["SettingsUiRefs"]
