from __future__ import annotations

from app.core import config


def test_runtime_paths_follow_isolated_home(isolated_runtime):
    runtime = config.runtime_dir()

    assert runtime == isolated_runtime
    assert config.settings_path() == isolated_runtime / "settings.json"
    assert config.cache_db_path() == isolated_runtime / "cache.db"
    assert config.log_path() == isolated_runtime / "logs" / "app.log"
    assert (isolated_runtime / "logs").is_dir()


def test_domain_allowlist_accepts_subdomains_case_insensitively():
    assert config.is_domain_allowed("EN.DICT.NAVER.COM")
    assert config.is_domain_allowed("audio.pstatic.net")
    assert not config.is_domain_allowed("example.com")
    assert not config.is_domain_allowed("")
