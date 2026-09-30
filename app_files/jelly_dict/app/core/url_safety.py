from __future__ import annotations

from urllib.parse import urlparse

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_GOOGLE_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


def safe_external_http_url(url: str | None) -> str | None:
    """Return a safe clickable external URL, or ``None`` for plain text.

    Source URLs may point at more than one dictionary host, so the trust
    boundary is the HTTP(S) scheme and a real hostname rather than a fixed
    allowlist. Embedded credentials and control characters are rejected.
    """
    candidate = (url or "").strip()
    if not candidate or any(ord(character) < 32 for character in candidate):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return candidate


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
