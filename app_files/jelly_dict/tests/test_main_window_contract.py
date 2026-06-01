from __future__ import annotations

from app.storage.settings_store import Settings
from app.ui.main_window import runtime_status_summary


def test_runtime_status_summary_balances_language_paths():
    summary = runtime_status_summary(
        Settings(
            excel_path_en="/tmp/vocab_en.xlsx",
            excel_path_ja="/tmp/vocab_ja_really_long_name.xlsx",
            provider="naver_crawler",
            cache_enabled=True,
        )
    )

    assert summary.startswith("EN: vocab_en.xlsx · JA: vocab_ja_really_long_name.xlsx")
    assert "Excel:" not in summary
    assert " / " not in summary
    assert summary.endswith("· Naver · cache on")
