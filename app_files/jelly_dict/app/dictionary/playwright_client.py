"""Playwright headless client for fetching Naver dictionary pages.

Per dev.md §16-A:
  - Network egress lives only in this module.
  - Domain whitelist is enforced via page.route().
  - Single global rate limiter throttles requests.

Uses Chromium headless. WebKit is closer to Safari, but its helper
processes can interfere with macOS Mission Control while lookups are
running. Run `playwright install chromium` to fetch the engine.

Threading model:
  Playwright's sync API can only be driven from the thread that started
  it. We run the browser inside a single dedicated daemon thread and
  communicate through a thread-safe queue, so any caller (UI, worker
  threads, tests) can call fetch() safely.
"""
from __future__ import annotations

import logging
import queue
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.core.config import is_domain_allowed
from app.core.errors import (
    DomainNotAllowedError,
    HttpStatusError,
    NetworkError,
    RateLimitedError,
)

log = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class _RateLimiter:
    """Throttle outbound requests to a single global rate.

    Adds a small uniform jitter (±20%) so the request cadence does not
    look like a robot's metronome to Naver's bot detection. Hard floor
    is 0.3 s — anything faster looks aggressive even with jitter.
    """

    HARD_FLOOR_SECONDS = 0.3
    JITTER_RATIO = 0.2

    def __init__(self, delay_seconds: float) -> None:
        self._delay = max(delay_seconds, self.HARD_FLOOR_SECONDS)
        self._lock = threading.Lock()
        self._last_at: float = 0.0

    def wait(self) -> None:
        with self._lock:
            jitter = self._delay * self.JITTER_RATIO
            target = self._delay + random.uniform(-jitter, jitter)
            now = time.monotonic()
            wait_for = target - (now - self._last_at)
            if wait_for > 0:
                time.sleep(wait_for)
            self._last_at = time.monotonic()

    def update_delay(self, delay_seconds: float) -> None:
        with self._lock:
            self._delay = max(delay_seconds, self.HARD_FLOOR_SECONDS)


@dataclass
class _FetchJob:
    url: str
    wait_selector: str | None
    wait_text: str | None
    timeout_ms: int
    result_event: threading.Event = field(default_factory=threading.Event)
    html: str | None = None
    error: BaseException | None = None


class _PlaywrightOwnerThread(threading.Thread):
    """Owns the Playwright instance + browser and serves fetch jobs."""

    def __init__(
        self,
        user_agent: str,
        headless: bool,
        ready_event: threading.Event,
        startup_error: list,
    ) -> None:
        super().__init__(name="playwright-owner", daemon=True)
        self._user_agent = user_agent
        self._headless = headless
        self._jobs: queue.Queue[_FetchJob | None] = queue.Queue()
        self._ready_event = ready_event
        self._startup_error = startup_error

    def submit(self, job: _FetchJob) -> None:
        self._jobs.put(job)

    def shutdown(self) -> None:
        self._jobs.put(None)

    def run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            self._startup_error.append(
                NetworkError(
                    "Playwright is not installed. "
                    "Run `pip install playwright && playwright install chromium`."
                )
            )
            self._ready_event.set()
            return

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=self._headless)
            context = browser.new_context(user_agent=self._user_agent)
        except Exception as exc:
            self._startup_error.append(NetworkError(f"browser launch failed: {exc}"))
            self._ready_event.set()
            return

        self._ready_event.set()
        try:
            while True:
                job = self._jobs.get()
                if job is None:
                    break
                self._handle(context, job)
        finally:
            try:
                context.close()
                browser.close()
                playwright.stop()
            except Exception as exc:
                log.warning("playwright shutdown warning: %s", exc)

    def _handle(self, context, job: _FetchJob) -> None:
        """Single-attempt fetch — never auto-retry. If anything fails the
        error is surfaced to the caller and we move on to the next job.

        Speed wins applied:
          - Block images/fonts/stylesheets/media at the route level
            (we only need DOM text, not the painted page).
          - Drop networkidle wait entirely; rely on the content selector.
          - Cap selector wait at 6s so we fail fast on broken pages.
        """
        page = None
        try:
            page = context.new_page()
            page.route("**/*", _enforce_whitelist)
            # ONE navigation attempt. No retry on failure.
            response = page.goto(
                job.url, wait_until="domcontentloaded", timeout=job.timeout_ms
            )
            if response is None:
                raise NetworkError("no response")
            status = response.status
            if status == 429:
                raise RateLimitedError(f"HTTP 429 on {job.url}")
            if status >= 400:
                raise HttpStatusError(status, f"{status} on {job.url}")

            # Wait until the dictionary content is in the DOM.
            # If the selector never appears we hand back whatever HTML
            # rendered — the parser will then surface parse_failed.
            if job.wait_selector:
                try:
                    page.wait_for_selector(
                        job.wait_selector,
                        timeout=min(job.timeout_ms, 9_000),
                        state="attached",
                    )
                except Exception as exc:
                    log.info("wait_selector %r not found: %s", job.wait_selector, exc)

            if job.wait_text:
                try:
                    page.wait_for_function(
                        f"document.body.innerText.includes({job.wait_text!r})",
                        timeout=min(job.timeout_ms, 4_000),
                    )
                except Exception as exc:
                    log.info("wait_text %r not seen: %s", job.wait_text, exc)

            job.html = page.content()
        except BaseException as exc:
            job.error = exc
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            job.result_event.set()


class PlaywrightClient:
    """Thread-safe headless fetcher with domain whitelist + rate limit.

    The browser starts lazily on the first fetch() and stays alive until
    stop() is called. Calls from any thread are queued and serialized
    onto a single owner thread that drives Playwright.
    """

    def __init__(
        self,
        request_delay_seconds: float = 3.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        headless: bool = True,
    ) -> None:
        self._limiter = _RateLimiter(request_delay_seconds)
        self._user_agent = user_agent
        self._headless = headless
        self._owner: _PlaywrightOwnerThread | None = None
        self._lock = threading.Lock()

    def update_delay(self, delay_seconds: float) -> None:
        self._limiter.update_delay(delay_seconds)

    def start(self) -> None:
        with self._lock:
            if self._owner is not None and self._owner.is_alive():
                return
            ready = threading.Event()
            startup_error: list = []
            self._owner = _PlaywrightOwnerThread(
                self._user_agent, self._headless, ready, startup_error
            )
            self._owner.start()
            ready.wait()
            if startup_error:
                self._owner = None
                raise startup_error[0]

    def stop(self) -> None:
        with self._lock:
            owner = self._owner
            self._owner = None
        if owner is not None:
            owner.shutdown()
            owner.join(timeout=5)

    def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout_ms: int = 12_000,
        wait_text: str | None = None,
    ) -> str:
        host = urlparse(url).hostname or ""
        if not is_domain_allowed(host):
            raise DomainNotAllowedError(host)

        if self._owner is None or not self._owner.is_alive():
            self.start()

        self._limiter.wait()
        job = _FetchJob(
            url=url,
            wait_selector=wait_selector,
            wait_text=wait_text,
            timeout_ms=timeout_ms,
        )
        assert self._owner is not None
        self._owner.submit(job)
        # Wait at most 2x the per-stage timeout to cover startup + waits.
        if not job.result_event.wait(timeout=(timeout_ms / 1000.0) * 3 + 10):
            raise NetworkError("fetch timed out waiting for owner thread")
        if job.error is not None:
            raise job.error
        return job.html or ""


# We only need DOM text, not painted pixels — aborting these resource
# types saves several MB on every Naver page load with no impact on
# data extraction. We deliberately leave stylesheets / scripts / xhr
# alone because the SPA depends on them to bootstrap.
_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})


def _enforce_whitelist(route, request):  # pragma: no cover - exercised via Playwright
    """Block any request whose host is not in the whitelist or whose
    resource type is irrelevant to text extraction."""
    url = request.url
    host = urlparse(url).hostname or ""
    if not is_domain_allowed(host):
        log.debug("blocked non-whitelisted request: %s", url)
        route.abort()
        return
    if request.resource_type in _BLOCKED_RESOURCE_TYPES:
        route.abort()
        return
    route.continue_()
