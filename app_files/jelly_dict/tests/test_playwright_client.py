from __future__ import annotations

from app.dictionary.playwright_client import _RateLimiter


def test_rate_limiter_sleeps_outside_lock(monkeypatch):
    limiter = _RateLimiter(1.0)
    limiter._last_at = 100.0

    monkeypatch.setattr("app.dictionary.playwright_client.random.uniform", lambda *_: 0.0)
    monkeypatch.setattr("app.dictionary.playwright_client.time.monotonic", lambda: 100.0)

    def fake_sleep(_seconds: float) -> None:
        assert limiter._lock.acquire(blocking=False)
        limiter._lock.release()

    monkeypatch.setattr("app.dictionary.playwright_client.time.sleep", fake_sleep)

    limiter.wait()


def test_rate_limiter_reserves_serial_slots(monkeypatch):
    limiter = _RateLimiter(1.0)
    limiter._last_at = 100.0
    sleeps: list[float] = []

    monkeypatch.setattr("app.dictionary.playwright_client.random.uniform", lambda *_: 0.0)
    monkeypatch.setattr("app.dictionary.playwright_client.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("app.dictionary.playwright_client.time.sleep", sleeps.append)

    limiter.wait()
    limiter.wait()

    assert sleeps == [1.0, 2.0]
