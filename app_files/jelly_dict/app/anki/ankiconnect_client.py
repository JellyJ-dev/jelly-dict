"""Tiny client for the AnkiConnect addon (https://ankiweb.net/shared/info/2055492159).

AnkiConnect listens on http://127.0.0.1:8765 by default and exposes a
JSON-RPC style API: every call is a POST with
    {"action": "...", "version": 6, "params": {...}}
and returns
    {"result": ..., "error": null}

We only need a handful of actions:
    - version          : connectivity test
    - findNotes        : look up note IDs by query string
    - notesInfo        : read note GUIDs / fields
    - deleteNotes      : remove notes by ID

Network notes (per dev.md §16-A):
  - This client only ever talks to localhost. It's the user's own Anki
    desktop running on their own machine.
  - We do NOT add ankiweb.net or any remote host. AnkiConnect itself
    refuses non-localhost binds by default.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from app.core.url_safety import require_loopback_http_url

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8765"
API_VERSION = 6


class AnkiConnectError(Exception):
    """Raised when AnkiConnect returns an error or is unreachable."""


class AnkiConnectClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 5.0) -> None:
        self._url = require_loopback_http_url(url, "AnkiConnect")
        self._timeout = timeout

    def _invoke(self, action: str, **params: Any) -> Any:
        payload = json.dumps(
            {"action": action, "version": API_VERSION, "params": params}
        ).encode("utf-8")
        req = urlrequest.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read()
        except (urlerror.URLError, OSError, TimeoutError) as exc:
            raise AnkiConnectError(
                f"AnkiConnect 접속 실패: Anki가 켜져 있고 AnkiConnect 애드온이 설치돼 있어야 합니다. ({exc})"
            ) from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AnkiConnectError(f"AnkiConnect 응답 파싱 실패: {exc}") from exc
        if data.get("error"):
            raise AnkiConnectError(str(data["error"]))
        return data.get("result")

    # ---------- public API ---------------------------------------------

    def is_available(self) -> bool:
        try:
            self._invoke("version")
            return True
        except AnkiConnectError:
            return False

    def find_notes_by_field(self, deck_prefix: str, field: str, value: str) -> list[int]:
        """Return note IDs whose `field` exactly matches `value` (within
        any deck whose name starts with deck_prefix)."""
        # AnkiConnect query syntax: deck:JellyDict::EN Word:apple
        safe_value = _quote(value)
        query_parts = [f'"{field}:{safe_value}"']
        if deck_prefix:
            query_parts.append(f'"deck:{_quote(deck_prefix)}*"')
        query = " ".join(query_parts)
        return list(self._invoke("findNotes", query=query) or [])

    def notes_info(self, note_ids: list[int]) -> list[dict[str, Any]]:
        if not note_ids:
            return []
        return list(self._invoke("notesInfo", notes=note_ids) or [])

    def delete_notes(self, note_ids: list[int]) -> int:
        if not note_ids:
            return 0
        self._invoke("deleteNotes", notes=note_ids)
        return len(note_ids)


def _quote(value: str) -> str:
    """Escape characters Anki's search syntax treats specially."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
