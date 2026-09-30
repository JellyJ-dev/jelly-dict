from __future__ import annotations

from app.anki.ankiconnect_client import AnkiConnectClient


class AnkiConnectClientFactory:
    def __call__(self, url: str) -> AnkiConnectClient:
        return AnkiConnectClient(url)
