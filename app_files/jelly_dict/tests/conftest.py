from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.models import Example, MeaningGroup, Sense, SubSense, VocabularyEntry
from app.storage.cache_store import CacheStore
from app.storage.settings_store import Settings


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path: Path) -> Iterator[Path]:
    """Redirect runtime data (settings, cache, logs) to a tmp dir per test."""
    monkeypatch.setenv("JELLY_DICT_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(default_excel_dir="")


@pytest.fixture
def mock_cache_store() -> CacheStore:
    return CacheStore()


@pytest.fixture
def sample_entry() -> VocabularyEntry:
    entry = VocabularyEntry(
        language="en",
        word="apple",
        reading="/apple/",
        part_of_speech=["Noun"],
        meaning_groups=[
            MeaningGroup(
                pos="Noun",
                senses=[
                    Sense(
                        number=1,
                        gloss="사과",
                        sub_senses=[
                            SubSense(
                                label="a",
                                gloss="과일",
                                examples=[
                                    Example(
                                        source_text="I ate an apple.",
                                        source_text_plain="I ate an apple.",
                                        translation_ko="나는 사과를 먹었다.",
                                    )
                                ],
                                synonyms=["fruit"],
                            )
                        ],
                    )
                ],
            )
        ],
        synonyms=["pome"],
        tags=["food"],
        source_url="https://en.dict.naver.com/#/entry/enko/apple",
    )
    entry.meanings_summary = "1. 사과"
    entry.examples_flat = [
        Example(
            source_text="I ate an apple.",
            source_text_plain="I ate an apple.",
            translation_ko="나는 사과를 먹었다.",
        )
    ]
    return entry


@pytest.fixture
def sample_japanese_entry() -> VocabularyEntry:
    return VocabularyEntry(
        language="ja",
        word="月日",
        reading="つきひ",
        part_of_speech=["명사"],
        meanings_summary="[명사] 1. 월일",
    )
