from __future__ import annotations

from pathlib import Path

from app.services.export_preflight import run_export_preflight
from app.storage.settings_store import Settings
from app.ui.export_options import (
    apply_audio_policy,
    build_export_plan,
    should_confirm_export,
)


def test_audio_policy_no_tts_and_remove_audio_disable_tts() -> None:
    settings = Settings(tts_enabled=True)

    no_tts = apply_audio_policy(settings, "en", "no_tts")
    assert no_tts.tts_enabled is False

    settings.tts_enabled = True
    remove = apply_audio_policy(settings, "en", "remove_audio")
    assert remove.tts_enabled is False


def test_smart_confirm_when_previous_export_had_tts_and_current_does_not() -> None:
    settings = Settings(
        anki_export_confirm_mode="smart",
        last_apkg_export_tts_enabled=True,
        tts_enabled=False,
    )
    plan = build_export_plan(
        settings,
        language="en",
        deck_name="JellyDict::EN",
        card_count=10,
    )

    assert should_confirm_export(
        settings,
        plan,
        has_blockers=False,
        has_warnings=False,
        output_exists=False,
    )


def test_smart_confirm_on_first_apkg_export() -> None:
    settings = Settings(anki_export_confirm_mode="smart")
    plan = build_export_plan(
        settings,
        language="en",
        deck_name="JellyDict::EN",
        card_count=10,
    )

    assert should_confirm_export(
        settings,
        plan,
        has_blockers=False,
        has_warnings=False,
        output_exists=False,
    )


def test_preflight_blocks_missing_excel_file(tmp_path: Path) -> None:
    settings = Settings(excel_path_en=str(tmp_path / "missing.xlsx"))
    plan = build_export_plan(
        settings,
        language="en",
        deck_name="JellyDict::EN",
        card_count=0,
    )

    result = run_export_preflight(settings, plan, output_path=tmp_path / "out.apkg")

    assert result.blockers
    assert any("Excel" in issue.message for issue in result.blockers)
    assert any("카드" in issue.message for issue in result.blockers)
