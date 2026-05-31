"""Tests for the AnkiConnect client. We monkeypatch urllib so nothing
actually leaves the test process. Confirms request format + error
mapping but does not require a running Anki instance."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from app.anki.ankiconnect_client import (
    AnkiConnectClient,
    AnkiConnectError,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def _patch_urlopen(monkeypatch, response_payload, captured: list):
    """Capture the outgoing request and return a canned response."""
    from urllib import request as urlrequest

    def fake_urlopen(req, timeout=None):
        captured.append(json.loads(req.data.decode("utf-8")))
        return _FakeResponse(response_payload)

    monkeypatch.setattr(
        "app.anki.ankiconnect_client.urlrequest.urlopen", fake_urlopen
    )


def test_is_available_true_when_version_responds(monkeypatch):
    captured: list = []
    _patch_urlopen(monkeypatch, {"result": 6, "error": None}, captured)
    client = AnkiConnectClient()
    assert client.is_available() is True
    assert captured[0]["action"] == "version"
    assert captured[0]["version"] == 6


def test_is_available_false_on_connection_error(monkeypatch):
    from urllib import error as urlerror

    def fake_urlopen(req, timeout=None):
        raise urlerror.URLError("connection refused")

    monkeypatch.setattr(
        "app.anki.ankiconnect_client.urlrequest.urlopen", fake_urlopen
    )

    client = AnkiConnectClient()
    assert client.is_available() is False


def test_find_notes_by_field_builds_search_query(monkeypatch):
    captured: list = []
    _patch_urlopen(monkeypatch, {"result": [101, 102], "error": None}, captured)
    client = AnkiConnectClient()
    ids = client.find_notes_by_field("JellyDict", "Word", "apple")
    assert ids == [101, 102]
    assert captured[0]["action"] == "findNotes"
    assert "Word:apple" in captured[0]["params"]["query"]
    assert "deck:JellyDict*" in captured[0]["params"]["query"]


def test_delete_notes_invokes_correct_action(monkeypatch):
    captured: list = []
    _patch_urlopen(monkeypatch, {"result": None, "error": None}, captured)
    client = AnkiConnectClient()
    deleted = client.delete_notes([1, 2, 3])
    assert deleted == 3
    assert captured[0]["action"] == "deleteNotes"
    assert captured[0]["params"]["notes"] == [1, 2, 3]


def test_delete_notes_empty_skips_call(monkeypatch):
    captured: list = []
    _patch_urlopen(monkeypatch, {"result": None, "error": None}, captured)
    client = AnkiConnectClient()
    assert client.delete_notes([]) == 0
    assert captured == [], "no HTTP call should be made for an empty list"


def test_error_payload_is_raised(monkeypatch):
    captured: list = []
    _patch_urlopen(
        monkeypatch, {"result": None, "error": "deck does not exist"}, captured
    )
    client = AnkiConnectClient()
    with pytest.raises(AnkiConnectError, match="deck does not exist"):
        client.find_notes_by_field("Missing", "Word", "x")


def test_quote_escapes_double_quotes_in_search_value(monkeypatch):
    """Words containing quotes (e.g. user free-text) must not break the
    Anki search syntax."""
    captured: list = []
    _patch_urlopen(monkeypatch, {"result": [], "error": None}, captured)
    client = AnkiConnectClient()
    client.find_notes_by_field("D", "Word", 'a"b')
    assert '\\"' in captured[0]["params"]["query"]


def test_remote_ankiconnect_url_is_rejected():
    with pytest.raises(ValueError, match="localhost"):
        AnkiConnectClient("https://example.com:8765")
