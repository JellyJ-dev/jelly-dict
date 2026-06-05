from __future__ import annotations

import pytest

from app.core.url_safety import require_google_vision_endpoint, require_loopback_http_url


def test_require_loopback_http_url_accepts_localhost_and_loopback():
    assert require_loopback_http_url("http://localhost:50021", "VOICEVOX")
    assert require_loopback_http_url("http://127.0.0.1:50021", "VOICEVOX")
    assert require_loopback_http_url("https://[::1]:50021", "VOICEVOX")


@pytest.mark.parametrize("url", ["ftp://localhost:1", "https://example.com", ""])
def test_require_loopback_http_url_rejects_non_local_targets(url: str):
    with pytest.raises(ValueError):
        require_loopback_http_url(url, "VOICEVOX")


def test_require_google_vision_endpoint_is_exact():
    endpoint = "https://vision.googleapis.com/v1/images:annotate"

    assert require_google_vision_endpoint(endpoint) == endpoint
    with pytest.raises(ValueError):
        require_google_vision_endpoint("https://evil.example/v1/images:annotate")
