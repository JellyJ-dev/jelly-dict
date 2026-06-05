from __future__ import annotations

import threading

from app.core.models import MeaningGroup, Sense, VocabularyEntry
from app.storage.cache_store import CacheStore


def test_upsert_and_get_round_trip(isolated_runtime):
    cache = CacheStore()
    entry = VocabularyEntry(language="en", word="Apple", reading="/ˈæp.əl/")
    cache.upsert(entry)

    fetched = cache.get("apple", "en")
    assert fetched is not None
    assert fetched.word == "Apple"
    assert fetched.reading == "/ˈæp.əl/"


def test_get_normalizes_japanese_key(isolated_runtime):
    cache = CacheStore()
    entry = VocabularyEntry(language="ja", word="カメラ")
    cache.upsert(entry)

    assert cache.get("ｶﾒﾗ", "ja") is not None


def test_upsert_updates_existing(isolated_runtime):
    cache = CacheStore()
    cache.upsert(VocabularyEntry(language="en", word="apple", memo="v1"))
    cache.upsert(VocabularyEntry(language="en", word="apple", memo="v2"))

    fetched = cache.get("apple", "en")
    assert fetched is not None
    assert fetched.memo == "v2"


def test_recent_lookups_dedup_and_order(isolated_runtime):
    cache = CacheStore()
    cache.remember_lookup("apple", "en")
    cache.remember_lookup("banana", "en")
    cache.remember_lookup("apple", "en")

    recent = cache.recent(limit=10)
    words = [r[1] for r in recent]
    assert "apple" in words
    assert "banana" in words
    assert len(set(words)) == len(words)


def test_clear_removes_all(isolated_runtime):
    cache = CacheStore()
    cache.upsert(VocabularyEntry(language="en", word="apple"))
    cache.clear()
    assert cache.get("apple", "en") is None


def test_delete_entries_targets_specific_keys(isolated_runtime):
    cache = CacheStore()
    cache.upsert(VocabularyEntry(language="en", word="apple"))
    cache.upsert(VocabularyEntry(language="en", word="banana"))
    cache.upsert(VocabularyEntry(language="ja", word="月日"))

    cache.delete_entries("en", {"apple"})
    assert cache.get("apple", "en") is None
    assert cache.get("banana", "en") is not None
    # Different language must not be touched.
    assert cache.get("月日", "ja") is not None


def test_delete_entries_no_keys_is_noop(isolated_runtime):
    cache = CacheStore()
    cache.upsert(VocabularyEntry(language="en", word="apple"))
    assert cache.delete_entries("en", set()) == 0
    assert cache.get("apple", "en") is not None


def test_app_state_round_trip(isolated_runtime):
    cache = CacheStore()

    cache.set_state("ui.last_view_mode", "ja")

    assert cache.get_state("ui.last_view_mode") == "ja"
    assert cache.get_state("missing") is None


def test_delete_recent_entries_targets_word_or_entry_word(isolated_runtime):
    cache = CacheStore()
    cache.remember_lookup("apple", "en", entry_word="Apple")
    cache.remember_lookup("banana", "en", entry_word="banana")
    cache.remember_lookup("蘇る", "ja", entry_word="蘇る·甦る")

    assert cache.delete_recent_entries("en", {"Apple"}) == 1
    assert cache.delete_recent_entries("ja", {"蘇る·甦る"}) == 1

    recent = cache.recent(limit=10)
    assert [(lang, word) for lang, word, *_ in recent] == [("en", "banana")]


def test_recent_clear_can_restore_snapshot(isolated_runtime):
    cache = CacheStore()
    cache.remember_lookup("apple", "en", entry_word="Apple")
    cache.remember_lookup("banana", "en", entry_word="banana")

    snapshot = cache.snapshot_recent_lookups()

    assert len(snapshot) == 2

    cache.clear_recent()
    assert cache.recent(limit=10) == []

    assert cache.restore_recent_lookups(snapshot) == 2
    restored = {(language, word, entry_word) for language, word, entry_word, _ in cache.recent(10)}
    assert restored == {("en", "apple", "Apple"), ("en", "banana", "banana")}


def test_recent_with_entries_returns_cached_payload(isolated_runtime):
    cache = CacheStore()
    entry = VocabularyEntry(language="en", word="apple")
    cache.upsert(entry)
    cache.remember_lookup("apple", "en", entry_word="apple")

    rows = cache.recent_with_entries(20)
    assert len(rows) == 1
    lang, word, entry_word, _, cached = rows[0]
    assert lang == "en"
    assert word == "apple"
    assert entry_word == "apple"
    assert cached is not None
    assert cached.word == "apple"


def test_recent_with_entries_falls_back_when_entry_word_differs(isolated_runtime):
    """If the user typed `蘇る` but the canonical entry was stored under
    `蘇る·甦る`, the JOIN should still find the cached entry by trying
    the entry_word first."""
    cache = CacheStore()
    entry = VocabularyEntry(language="ja", word="蘇る·甦る")
    cache.upsert(entry)
    cache.remember_lookup("蘇る", "ja", entry_word="蘇る·甦る")

    rows = cache.recent_with_entries(20)
    assert len(rows) == 1
    _, typed_word, entry_word, _, cached = rows[0]
    assert typed_word == "蘇る"
    assert entry_word == "蘇る·甦る"
    assert cached is not None
    assert cached.word == "蘇る·甦る"


def test_stale_naver_english_cache_is_ignored(isolated_runtime):
    cache = CacheStore()
    entry = VocabularyEntry(
        language="en",
        word="artifact",
        source_provider="naver_en",
        meaning_groups=[
            MeaningGroup(
                pos="Noun",
                senses=[Sense(number=1, gloss="특히 美 (= artefact)")],
            )
        ],
    )
    cache.upsert(entry)
    cache.remember_lookup("artifact", "en", entry_word="artifact")

    assert cache.get("artifact", "en") is None
    recent = cache.recent_with_entries(10)
    assert len(recent) == 1
    assert recent[0][-1] is None


def test_cache_store_connection_can_be_shared_across_threads(isolated_runtime):
    cache = CacheStore()
    errors: list[BaseException] = []

    def upsert(index: int) -> None:
        try:
            cache.upsert(VocabularyEntry(language="en", word=f"word-{index}"))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=upsert, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert cache.get("word-5", "en") is not None
