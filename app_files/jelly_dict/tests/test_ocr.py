from __future__ import annotations


import pytest

from app.ocr import OcrResult, OcrToken, build_ocr_provider, normalize_ocr_tokens
from app.ocr import temp_files


def test_normalize_ocr_tokens_filters_duplicates_and_punctuation() -> None:
    tokens = normalize_ocr_tokens(
        [
            OcrToken(" apple ", 0.9),
            OcrToken("APPLE", 0.8),
            OcrToken("!!!", 0.7),
            OcrToken("りんご", 0.6),
            OcrToken("出来事 できごと", 0.5),
            "",
        ]
    )

    assert [token.text for token in tokens] == ["apple", "りんご", "出来事", "できごと"]
    assert tokens[0].confidence == pytest.approx(0.9)


def test_ocr_provider_selection_defaults_to_apple_vision() -> None:
    provider = build_ocr_provider(None)

    assert provider.__class__.__name__ == "AppleVisionOcrProvider"


def test_google_vision_provider_requires_api_key(monkeypatch) -> None:
    # Ensure no env-var fallback leaks a key into this test.
    monkeypatch.delenv("JELLY_DICT_GOOGLE_VISION_API_KEY", raising=False)
    from app.storage import secret_store

    monkeypatch.setattr(secret_store, "get", lambda name: None)
    with pytest.raises(RuntimeError, match="API"):
        build_ocr_provider("google_vision")


def test_google_vision_provider_constructs_with_key(monkeypatch) -> None:
    monkeypatch.setenv("JELLY_DICT_GOOGLE_VISION_API_KEY", "test-key-xyz")
    provider = build_ocr_provider("google_vision")
    assert provider.__class__.__name__ == "GoogleVisionOcrProvider"
    # Repr must mask the key.
    assert "test-key-xyz" not in repr(provider)
    assert "***" in repr(provider)


def test_google_vision_rejects_nonofficial_endpoint() -> None:
    from app.ocr.google_vision import GoogleVisionOcrProvider

    with pytest.raises(ValueError, match="공식"):
        GoogleVisionOcrProvider("key", "https://example.com/v1/images:annotate")


def test_ocr_result_keeps_worker_payload_shape() -> None:
    result = OcrResult([OcrToken("dragon", 0.95)])

    assert result.tokens[0].text == "dragon"
    assert result.tokens[0].confidence == pytest.approx(0.95)


def test_ocr_temp_cleanup_removes_only_paste_images(tmp_path) -> None:
    directory = temp_files.temp_dir(tmp_path)
    directory.mkdir(parents=True)
    old = directory / "paste-old.png"
    old.write_bytes(b"png")
    keep = directory / "manual.png"
    keep.write_bytes(b"png")

    assert temp_files.cleanup_temp_dir(tmp_path) == 1
    assert not old.exists()
    assert keep.exists()


def test_ocr_temp_remove_file_is_idempotent(tmp_path) -> None:
    path = tmp_path / "paste-one.png"
    path.write_bytes(b"png")

    temp_files.remove_temp_file(path)
    temp_files.remove_temp_file(path)

    assert not path.exists()
