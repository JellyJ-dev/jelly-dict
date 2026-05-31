"""Google Cloud Vision OCR provider.

Calls the public REST endpoint via stdlib ``urllib`` so we don't bring in
the heavyweight ``google-cloud-vision`` SDK. The API key is provided by
the user and read from the OS keychain at construction time — never
logged, never persisted to settings.json.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from app.core.url_safety import require_google_vision_endpoint
from app.ocr.base import OcrResult, OcrToken, normalize_ocr_tokens

logger = logging.getLogger(__name__)

_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)


class GoogleVisionOcrProvider:
    def __init__(self, api_key: str, endpoint: str) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        # Hold the key as a private attribute. ``__repr__`` is masked below.
        self._api_key = api_key
        self._endpoint = require_google_vision_endpoint(endpoint)

    def __repr__(self) -> str:
        return "GoogleVisionOcrProvider(api_key=***)"

    def extract(self, image_path: Path) -> OcrResult:
        path = Path(image_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        body = json.dumps(
            {
                "requests": [
                    {
                        "image": {"content": encoded},
                        "features": [
                            {"type": "TEXT_DETECTION", "maxResults": 50}
                        ],
                        "imageContext": {
                            "languageHints": ["en", "ja", "ko"],
                        },
                    }
                ]
            }
        ).encode("utf-8")

        # Key goes in the URL as ``?key=...`` per Google's REST docs. We
        # never write this URL to logs.
        url = f"{self._endpoint}?key={self._api_key}"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Don't echo the URL (contains key) — only the status code.
            raise RuntimeError(
                f"Google Vision OCR 실패: HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Google Vision OCR 네트워크 실패: {exc.reason}"
            ) from None

        return _parse_response(payload)


def test_api_key(api_key: str, endpoint: str) -> None:
    """Make a tiny Google Vision request to validate a user-provided key."""
    if not api_key:
        raise RuntimeError("키 미설정")
    endpoint = require_google_vision_endpoint(endpoint)

    tiny_png = base64.b64decode(_TINY_PNG_BASE64)
    body = json.dumps(
        {
            "requests": [
                {
                    "image": {
                        "content": base64.b64encode(tiny_png).decode("ascii")
                    },
                    "features": [{"type": "TEXT_DETECTION"}],
                }
            ]
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint}?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} — 키를 확인하세요") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"네트워크 실패: {exc.reason}") from None


def _parse_response(payload: dict) -> OcrResult:
    responses = payload.get("responses") or []
    if not responses:
        return OcrResult(tokens=[])
    first = responses[0] or {}
    if "error" in first:
        msg = first["error"].get("message", "unknown")
        raise RuntimeError(f"Google Vision OCR 응답 오류: {msg}")

    raw: list[OcrToken] = []
    # textAnnotations[0] is the full block; subsequent entries are word-level.
    text_annotations = first.get("textAnnotations") or []
    for entry in text_annotations[1:]:
        text = entry.get("description") or ""
        if text:
            raw.append(OcrToken(text=text, confidence=0.0))
    if not raw and text_annotations:
        # Only the full-block annotation — split by whitespace.
        full = text_annotations[0].get("description") or ""
        for piece in full.split():
            raw.append(OcrToken(text=piece, confidence=0.0))
    return OcrResult(tokens=normalize_ocr_tokens(raw))
