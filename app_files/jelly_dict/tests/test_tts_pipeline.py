from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.anki.tts import cache as tts_cache
from app.anki.tts.base import NoTTSProvider, ProviderInfo, TTSResult


@dataclass
class _Settings:
    tts_enabled: bool = True
    tts_engine_en: str = "fake"
    tts_engine_ja: str = "fake"
    tts_voice_en: str = "v_en"
    tts_voice_ja: str = "v_ja"
    tts_play_front: bool = True
    tts_play_back: bool = True
    tts_play_examples: bool = False
    tts_bitrate: str = "96k"
    tts_sample_rate: int = 44100
    voicevox_url: str = "http://127.0.0.1:50021"


class _FakeProvider:
    """In-memory provider used to drive the pipeline without external deps."""
    requires_credit = False
    credit = ""

    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            id="fake", display_name="Fake", available=True,
            voices_en=("v_en",), voices_ja=("v_ja",),
            requires_credit=cls.requires_credit, license_note="",
        )

    @classmethod
    def is_available(cls):
        return True

    def __init__(self, settings):
        self._settings = settings
        self.calls = 0

    def synthesize(self, text, *, language, voice, out_path):
        self.calls += 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake-mp3")
        return TTSResult(
            path=out_path,
            engine_id="fake",
            voice=voice,
            requires_credit=self.requires_credit,
            credit_text=self.credit,
        )


def _patch_registry(monkeypatch, provider_cls=_FakeProvider):
    import app.anki.tts as tts_pkg
    from app.anki.tts import pipeline as pipeline_mod

    fake = lambda: {"fake": provider_cls}
    monkeypatch.setattr(tts_pkg, "list_provider_classes", fake)
    # pipeline imports build_provider/get_provider_info at module-load time;
    # rebind the symbols it captured.
    monkeypatch.setattr(pipeline_mod, "build_provider", tts_pkg.build_provider)
    monkeypatch.setattr(pipeline_mod, "get_provider_info", tts_pkg.get_provider_info)


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("JELLY_DICT_HOME", str(tmp_path))
    yield tmp_path


def test_cache_path_is_deterministic(isolated_runtime):
    p1 = tts_cache.cache_path("en", "fake", "alpha", "hello")
    p2 = tts_cache.cache_path("en", "fake", "alpha", "hello")
    assert p1 == p2
    assert p1.name.startswith("en_fake_alpha_")
    assert p1.suffix == ".mp3"


def test_cache_path_differs_by_text(isolated_runtime):
    a = tts_cache.cache_path("en", "fake", "alpha", "hello")
    b = tts_cache.cache_path("en", "fake", "alpha", "world")
    assert a != b


def test_cache_path_differs_by_output_settings(isolated_runtime):
    a = tts_cache.cache_path(
        "en", "fake", "alpha", "hello", bitrate="96k", sample_rate=44100
    )
    b = tts_cache.cache_path(
        "en", "fake", "alpha", "hello", bitrate="128k", sample_rate=44100
    )
    c = tts_cache.cache_path(
        "en", "fake", "alpha", "hello", bitrate="96k", sample_rate=48000
    )
    assert a != b
    assert a != c


def test_pipeline_disabled_returns_none(isolated_runtime, monkeypatch):
    _patch_registry(monkeypatch)
    from app.anki.tts.pipeline import TTSPipeline

    s = _Settings(tts_enabled=False)
    pipeline = TTSPipeline(s)
    assert pipeline.synthesize("hello", "en") is None


def test_pipeline_writes_audio_and_caches(isolated_runtime, monkeypatch):
    _patch_registry(monkeypatch)
    from app.anki.tts.pipeline import TTSBatch, TTSPipeline

    s = _Settings()
    pipeline = TTSPipeline(s)
    batch = TTSBatch()

    p1 = pipeline.synthesize("hello", "en", batch)
    assert p1 is not None and p1.exists()
    # Same text -> cache hit, no second synth call.
    p2 = pipeline.synthesize("hello", "en", batch)
    assert p2 == p1
    fake = pipeline._providers["fake"]
    assert fake.calls == 1
    assert p1 in batch.media_paths
    assert batch.media_paths.count(p1) == 1


def test_pipeline_regenerates_empty_cached_audio(isolated_runtime, monkeypatch):
    _patch_registry(monkeypatch)
    from app.anki.tts.pipeline import TTSPipeline

    s = _Settings()
    path = tts_cache.cache_path(
        "en",
        "fake",
        "v_en",
        "hello",
        bitrate=s.tts_bitrate,
        sample_rate=s.tts_sample_rate,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")

    pipeline = TTSPipeline(s)
    result = pipeline.synthesize("hello", "en")

    assert result == path
    assert path.read_bytes() == b"fake-mp3"


def test_pipeline_removes_empty_audio_after_provider_failure(
    isolated_runtime,
    monkeypatch,
):
    class _BrokenPartial(_FakeProvider):
        def synthesize(self, text, *, language, voice, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"")
            raise RuntimeError("boom")

    _patch_registry(monkeypatch, _BrokenPartial)
    from app.anki.tts.pipeline import TTSPipeline

    s = _Settings()
    path = tts_cache.cache_path(
        "en",
        "fake",
        "v_en",
        "hello",
        bitrate=s.tts_bitrate,
        sample_rate=s.tts_sample_rate,
    )
    pipeline = TTSPipeline(s)

    assert pipeline.synthesize("hello", "en") is None
    assert not path.exists()


def test_pipeline_removes_nonempty_audio_after_provider_failure(
    isolated_runtime,
    monkeypatch,
):
    class _BrokenPartial(_FakeProvider):
        def synthesize(self, text, *, language, voice, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"partial")
            raise RuntimeError("boom")

    _patch_registry(monkeypatch, _BrokenPartial)
    from app.anki.tts.pipeline import TTSPipeline

    s = _Settings()
    path = tts_cache.cache_path(
        "en",
        "fake",
        "v_en",
        "hello",
        bitrate=s.tts_bitrate,
        sample_rate=s.tts_sample_rate,
    )
    pipeline = TTSPipeline(s)

    assert pipeline.synthesize("hello", "en") is None
    assert not path.exists()


def test_pipeline_failure_swallowed(isolated_runtime, monkeypatch):
    class _Broken(_FakeProvider):
        def synthesize(self, text, *, language, voice, out_path):
            raise RuntimeError("boom")

    _patch_registry(monkeypatch, _Broken)
    from app.anki.tts.pipeline import TTSPipeline

    pipeline = TTSPipeline(_Settings())
    assert pipeline.synthesize("hello", "en") is None


def test_pipeline_collects_credit_for_voicevox_like_provider(
    isolated_runtime, monkeypatch
):
    class _CreditProvider(_FakeProvider):
        requires_credit = True
        credit = "VOICEVOX:四国めたん"

    _patch_registry(monkeypatch, _CreditProvider)
    from app.anki.tts.pipeline import TTSBatch, TTSPipeline

    pipeline = TTSPipeline(_Settings())
    batch = TTSBatch()
    pipeline.synthesize("こんにちは", "ja", batch)
    assert "VOICEVOX:四国めたん" in batch.credits


def test_no_tts_provider_raises_on_synth():
    p = NoTTSProvider()
    with pytest.raises(RuntimeError):
        p.synthesize("x", language="en", voice="v", out_path=Path("/tmp/x"))
