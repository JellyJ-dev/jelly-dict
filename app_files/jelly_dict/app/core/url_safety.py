from __future__ import annotations

from urllib.parse import urlparse


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_GOOGLE_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


def require_loopback_http_url(url: str, label: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or host not in _LOOPBACK_HOSTS:
        raise ValueError(f"{label} URL은 localhost/127.0.0.1만 사용할 수 있습니다.")
    return url


def require_google_vision_endpoint(endpoint: str) -> str:
    if (endpoint or "").strip() != _GOOGLE_VISION_ENDPOINT:
        raise ValueError("Google Vision endpoint는 공식 REST endpoint만 사용할 수 있습니다.")
    return endpoint
