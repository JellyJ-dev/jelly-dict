"""Playwright headless client for fetching Naver dictionary pages.

Network ownership contract:
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
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import parse_qs, urlparse

from app.core.config import is_domain_allowed
from app.core.errors import (
    DomainNotAllowedError,
    HttpStatusError,
    NetworkError,
    ParseError,
    RateLimitedError,
)

log = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class PlaywrightState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


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
            next_at = self._last_at + target
            wait_for = max(0.0, next_at - now)
            self._last_at = next_at if wait_for > 0 else now
        if wait_for > 0:
            time.sleep(wait_for)

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
    timings: FetchTimings = field(default_factory=lambda: FetchTimings())
    response_match: JsonResponseMatch | None = None
    data: dict | None = None
    force_refresh: bool = False
    from_cache: bool = False
    limiter: _RateLimiter | None = None


@dataclass(frozen=True)
class JsonResponseMatch:
    path: str
    parameter: str
    value: str

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        actual = (query.get(self.parameter) or [""])[0]
        return (
            parsed.scheme == "https"
            and parsed.hostname == "en.dict.naver.com"
            and parsed.path == self.path
            and _response_key(actual) == _response_key(self.value)
            and not query.get("range")
        )

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return self.path, self.parameter, _response_key(self.value)


@dataclass(frozen=True)
class JsonFetchResult:
    data: dict
    timings: FetchTimings
    from_cache: bool = False


@dataclass(frozen=True)
class FetchTimings:
    navigation_ms: float = 0.0
    dom_ready_ms: float = 0.0
    selector_ms: float = 0.0
    text_ms: float = 0.0
    content_ms: float = 0.0
    parse_ms: float = 0.0
    total_ms: float = 0.0

    def with_parse(self, parse_ms: float) -> FetchTimings:
        return FetchTimings(
            navigation_ms=self.navigation_ms,
            dom_ready_ms=self.dom_ready_ms,
            selector_ms=self.selector_ms,
            text_ms=self.text_ms,
            content_ms=self.content_ms,
            parse_ms=parse_ms,
            total_ms=self.total_ms + parse_ms,
        )


@dataclass(frozen=True)
class FetchResult:
    html: str
    timings: FetchTimings


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
        self._queue_lock = threading.Lock()
        self._stopping = False
        self._json_page = None
        self._json_cache: dict[tuple[str, str, str], dict] = {}
        self._json_session_started = 0.0

    def submit(self, job: _FetchJob) -> None:
        with self._queue_lock:
            if self._stopping:
                raise NetworkError("browser owner is stopping; fetch cancelled")
            self._jobs.put(job)

    def shutdown(self) -> None:
        with self._queue_lock:
            if self._stopping:
                return
            self._stopping = True
            self._jobs.put(None)

    def run(self) -> None:
        playwright = None
        browser = None
        context = None
        ready_announced = False
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:  # pragma: no cover
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
            ready_announced = True
            self._ready_event.set()
            while True:
                job = self._jobs.get()
                if job is None:
                    break
                self._handle(context, job)
        except Exception as exc:
            if not ready_announced:
                self._startup_error.append(NetworkError(f"browser launch failed: {exc}"))
            else:
                log.warning("playwright owner failed: %s", exc)
        finally:
            if not ready_announced:
                self._ready_event.set()
            self._reset_json_session()
            if context is not None:
                try:
                    context.close()
                except Exception as exc:
                    log.warning("playwright context close warning: %s", exc)
            if browser is not None:
                try:
                    browser.close()
                except Exception as exc:
                    log.warning("playwright browser close warning: %s", exc)
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception as exc:
                    log.warning("playwright runtime stop warning: %s", exc)

    def _handle(self, context, job: _FetchJob) -> None:
        """Single-attempt fetch — never auto-retry. If anything fails the
        error is surfaced to the caller and we move on to the next job.

        Speed wins applied:
          - Block images/fonts/stylesheets/media at the route level
            (we only need DOM text, not the painted page).
          - Drop networkidle wait entirely; rely on the content selector.
          - Prefer the caller's content selector/text over the browser load
            event, using one bounded readiness budget.
        """
        if job.response_match is not None:
            self._handle_json(context, job)
            return
        page = None
        started = time.perf_counter()
        navigation_ms = 0.0
        dom_ready_ms = 0.0
        selector_ms = 0.0
        text_ms = 0.0
        content_ms = 0.0
        try:
            page = context.new_page()
            page.route("**/*", _enforce_whitelist)
            # ONE navigation attempt. No retry on failure.
            stage_started = time.perf_counter()
            response = page.goto(job.url, wait_until="commit", timeout=job.timeout_ms)
            navigation_ms = _elapsed_ms(stage_started)
            if response is None:
                raise NetworkError("no response")
            status = response.status
            if status == 429:
                raise RateLimitedError(f"HTTP 429 on {job.url}")
            if status >= 400:
                raise HttpStatusError(status, f"{status} on {job.url}")

            # Naver's SPA can keep ``domcontentloaded`` pending after the
            # dictionary result is usable (and occasionally the inverse on a
            # cold load).  Waiting for that event first used to consume the
            # entire readiness budget, leaving only 1ms for the selector and
            # handing an empty shell to the parser.  A caller-provided content
            # gate is authoritative; only fall back to DOM-ready when no such
            # gate exists.
            has_content_gate = bool(job.wait_selector or job.wait_text)
            readiness_timeout_ms = (
                job.timeout_ms if has_content_gate else min(job.timeout_ms, 4_000)
            )
            readiness_deadline = time.perf_counter() + readiness_timeout_ms / 1000.0

            if not job.wait_selector and not job.wait_text:
                stage_started = time.perf_counter()
                try:
                    page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=_remaining_ms(readiness_deadline),
                    )
                except Exception as exc:
                    log.info("domcontentloaded not reached: %s", exc)
                dom_ready_ms = _elapsed_ms(stage_started)

            # Wait until the dictionary content is in the DOM.
            # If the selector never appears we hand back whatever HTML
            # rendered — the parser will then surface parse_failed.
            if job.wait_selector:
                stage_started = time.perf_counter()
                try:
                    page.wait_for_selector(
                        job.wait_selector,
                        timeout=_remaining_ms(readiness_deadline),
                        state="attached",
                    )
                except Exception as exc:
                    log.info("wait_selector %r not found: %s", job.wait_selector, exc)
                selector_ms = _elapsed_ms(stage_started)

            if job.wait_text:
                stage_started = time.perf_counter()
                try:
                    page.wait_for_function(
                        f"document.body.innerText.includes({job.wait_text!r})",
                        timeout=_remaining_ms(readiness_deadline),
                    )
                except Exception as exc:
                    log.info("wait_text %r not seen: %s", job.wait_text, exc)
                text_ms = _elapsed_ms(stage_started)

            stage_started = time.perf_counter()
            job.html = page.content()
            content_ms = _elapsed_ms(stage_started)
        except BaseException as exc:
            job.error = _fetch_error(exc)
        finally:
            job.timings = FetchTimings(
                navigation_ms=navigation_ms,
                dom_ready_ms=dom_ready_ms,
                selector_ms=selector_ms,
                text_ms=text_ms,
                content_ms=content_ms,
                total_ms=_elapsed_ms(started),
            )
            log.info(
                "playwright_fetch_timing navigation_ms=%.1f dom_ready_ms=%.1f "
                "selector_ms=%.1f text_ms=%.1f content_ms=%.1f total_ms=%.1f "
                "error=%s",
                navigation_ms,
                dom_ready_ms,
                selector_ms,
                text_ms,
                content_ms,
                job.timings.total_ms,
                type(job.error).__name__ if job.error is not None else "none",
            )
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            job.result_event.set()

    def _reset_json_session(self) -> None:
        page, self._json_page = self._json_page, None
        self._json_cache.clear()
        if page is not None:
            try:
                page.close()
            except Exception:
                pass

    def _handle_json(self, context, job: _FetchJob) -> None:
        """Observe Naver's own response on a reusable, owner-thread-only page.

        Naver memoizes routes in JS, so retain observed responses for this page.
        Eviction/expiry must reset BOTH caches together, otherwise revisiting a
        route can wait forever for a request Naver no longer sends.
        """
        started = time.perf_counter()
        navigation_ms = response_ms = content_ms = 0.0
        match = job.response_match
        assert match is not None
        try:
            if (
                job.force_refresh
                or time.monotonic() - self._json_session_started > 300
                or len(self._json_cache) >= 64
                or (self._json_page is not None and self._json_page.is_closed())
            ):
                self._reset_json_session()
            cached = self._json_cache.get(match.cache_key)
            if cached is not None:
                job.data = deepcopy(cached)
                job.from_cache = True
                return
            if job.limiter is not None:
                job.limiter.wait()
            if self._json_page is None:
                self._json_page = context.new_page()
                self._json_page.route("**/*", _enforce_whitelist)
                self._json_session_started = time.monotonic()
            page = self._json_page
            stage = time.perf_counter()
            with page.expect_response(
                lambda response: match.matches(response.url), timeout=job.timeout_ms
            ) as pending:
                navigation = page.goto(job.url, wait_until="commit", timeout=job.timeout_ms)
                navigation_ms = _elapsed_ms(stage)
                # Hash navigation normally returns None on this reused page.
                if navigation is not None:
                    _check_status(navigation.status, job.url)
            response = pending.value
            response_ms = max(0.0, _elapsed_ms(stage) - navigation_ms)
            _check_status(response.status, response.url)
            stage = time.perf_counter()
            try:
                data = response.json()
            except ValueError as exc:
                raise ParseError("dictionary response is not JSON") from exc
            if not isinstance(data, dict):
                raise ParseError("dictionary response is not an object")
            self._json_cache[match.cache_key] = data
            job.data = deepcopy(data)
            content_ms = _elapsed_ms(stage)
        except BaseException as exc:
            job.error = _fetch_error(exc)
            self._reset_json_session()
        finally:
            job.timings = FetchTimings(
                navigation_ms=navigation_ms,
                selector_ms=response_ms,
                content_ms=content_ms,
                total_ms=_elapsed_ms(started),
            )
            log.info(
                "naver_json_fetch path=%s key=%s navigation_ms=%.1f response_ms=%.1f "
                "total_ms=%.1f cache=%s error=%s",
                match.path,
                match.value,
                navigation_ms,
                response_ms,
                job.timings.total_ms,
                job.from_cache,
                type(job.error).__name__ if job.error else "none",
            )
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
        startup_timeout_seconds: float = 20.0,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        self._limiter = _RateLimiter(request_delay_seconds)
        self._user_agent = user_agent
        self._headless = headless
        self._startup_timeout_seconds = max(0.01, startup_timeout_seconds)
        self._stop_timeout_seconds = max(0.01, stop_timeout_seconds)
        self._owner: _PlaywrightOwnerThread | None = None
        self._state = PlaywrightState.STOPPED
        self._condition = threading.Condition()
        self._last_start_wait_ms = 0.0

    @property
    def state(self) -> PlaywrightState:
        with self._condition:
            return self._state

    def update_delay(self, delay_seconds: float) -> None:
        self._limiter.update_delay(delay_seconds)

    @property
    def last_start_wait_ms(self) -> float:
        with self._condition:
            return self._last_start_wait_ms

    def start(self) -> None:
        with self._condition:
            if self._state is PlaywrightState.RUNNING:
                self._last_start_wait_ms = 0.0
                return
            if self._state is PlaywrightState.STARTING:
                wait_started = time.perf_counter()
                ready = self._condition.wait_for(
                    lambda: self._state is not PlaywrightState.STARTING,
                    timeout=self._startup_timeout_seconds,
                )
                self._last_start_wait_ms = _elapsed_ms(wait_started)
                log.info(
                    "playwright_start_race_wait_ms=%.1f",
                    self._last_start_wait_ms,
                )
                if not ready:
                    raise NetworkError("browser startup timed out")
                if self._state is PlaywrightState.RUNNING:
                    return
                raise NetworkError(f"browser is {self._state.value}")
            if self._state is PlaywrightState.STOPPING:
                raise NetworkError("browser is stopping; start cancelled")
            if self._owner is not None and self._owner.is_alive():
                raise NetworkError("previous browser owner is still alive; start cancelled")
            ready = threading.Event()
            startup_error: list = []
            owner = _PlaywrightOwnerThread(self._user_agent, self._headless, ready, startup_error)
            self._owner = owner
            self._state = PlaywrightState.STARTING
            owner.start()

        if not ready.wait(timeout=self._startup_timeout_seconds):
            owner.shutdown()
            owner.join(timeout=self._stop_timeout_seconds)
            with self._condition:
                if self._owner is owner:
                    self._state = PlaywrightState.FAILED
                    if not owner.is_alive():
                        self._owner = None
                    self._condition.notify_all()
            raise NetworkError("browser startup timed out")

        with self._condition:
            if self._owner is not owner:
                raise NetworkError("browser startup was cancelled")
            if self._state is PlaywrightState.STOPPING:
                self._condition.notify_all()
                raise NetworkError("browser startup was cancelled by stop")
            if startup_error:
                self._state = PlaywrightState.FAILED
                if not owner.is_alive():
                    self._owner = None
                self._condition.notify_all()
                raise startup_error[0]
            if not owner.is_alive():
                self._state = PlaywrightState.FAILED
                self._owner = None
                self._condition.notify_all()
                raise NetworkError("browser owner exited during startup")
            self._state = PlaywrightState.RUNNING
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            owner = self._owner
            if owner is None:
                self._state = PlaywrightState.STOPPED
                self._condition.notify_all()
                return
            self._state = PlaywrightState.STOPPING
            owner.shutdown()
        owner.join(timeout=self._stop_timeout_seconds)
        with self._condition:
            if self._owner is not owner:
                return
            if owner.is_alive():
                # Retain ownership: starting a second Playwright runtime while
                # the first still owns browser objects is unsafe.
                self._state = PlaywrightState.STOPPING
            else:
                self._owner = None
                self._state = PlaywrightState.STOPPED
            self._condition.notify_all()

    def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout_ms: int = 12_000,
        wait_text: str | None = None,
    ) -> str:
        return self.fetch_with_metrics(
            url,
            wait_selector=wait_selector,
            timeout_ms=timeout_ms,
            wait_text=wait_text,
        ).html

    def fetch_with_metrics(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout_ms: int = 12_000,
        wait_text: str | None = None,
    ) -> FetchResult:
        host = urlparse(url).hostname or ""
        if not is_domain_allowed(host):
            raise DomainNotAllowedError(host)

        self.start()

        self._limiter.wait()
        job = _FetchJob(
            url=url,
            wait_selector=wait_selector,
            wait_text=wait_text,
            timeout_ms=timeout_ms,
        )
        self._submit_fetch(job)
        return FetchResult(job.html or "", job.timings)

    def fetch_naver_json(
        self,
        url: str,
        match: JsonResponseMatch,
        *,
        timeout_ms: int = 12_000,
        force_refresh: bool = False,
    ) -> JsonFetchResult:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "en.dict.naver.com":
            raise DomainNotAllowedError(parsed.hostname or "")
        self.start()
        job = _FetchJob(
            url,
            None,
            None,
            timeout_ms,
            response_match=match,
            force_refresh=force_refresh,
            limiter=self._limiter,
        )
        self._submit_fetch(job)
        if job.data is None:
            raise ParseError("missing dictionary response")
        return JsonFetchResult(job.data, job.timings, job.from_cache)

    def _submit_fetch(self, job: _FetchJob) -> None:
        with self._condition:
            owner = self._owner
            if self._state is not PlaywrightState.RUNNING or owner is None or not owner.is_alive():
                raise NetworkError(f"browser is {self._state.value}; fetch cancelled")
            # State check and owner queue submit are atomic with stop().
            owner.submit(job)
        # Bound caller waiting even if an owner-side Playwright call wedges.
        delay_budget = job.limiter._delay * 1.2 if job.limiter else 0.0
        if not job.result_event.wait(timeout=(job.timeout_ms / 1000.0) * 3 + 10 + delay_budget):
            raise NetworkError("fetch timed out waiting for owner thread")
        if job.error is not None:
            raise job.error


def _response_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _check_status(status: int, url: str) -> None:
    if status == 429:
        raise RateLimitedError(f"HTTP 429 on {url}")
    if status >= 400:
        raise HttpStatusError(status, f"HTTP {status} on {url}")


def _fetch_error(exc: BaseException) -> BaseException:
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        return exc

    if isinstance(exc, PlaywrightError):
        return NetworkError(str(exc))
    return exc


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _remaining_ms(deadline: float) -> int:
    return max(1, int((deadline - time.perf_counter()) * 1000.0))


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
