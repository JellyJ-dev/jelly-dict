"""Lazy macOS spelling suggestions, with native callbacks marshalled to Qt."""

from __future__ import annotations

import logging
import re
import sys
import weakref
from collections import OrderedDict

from PySide6 import QtCore

log = logging.getLogger(__name__)
MAX_CANDIDATES = 5
_ENGLISH_INPUT = re.compile(r"[A-Za-z]+(?:[ '\u2019-][A-Za-z]+)*")


def _native_checker():
    # AppKit is intentionally absent from startup and successful lookup paths.
    from AppKit import NSSpellChecker, NSTextCheckingOrthographyKey
    from Foundation import NSOrthography, NSTextCheckingTypeSpelling

    checker = NSSpellChecker.sharedSpellChecker()
    languages = set(checker.availableLanguages())
    language = next((value for value in ("en", "en_US", "en_GB") if value in languages), None)
    if language is None:
        raise RuntimeError("English spelling service unavailable")
    options = {
        NSTextCheckingOrthographyKey: NSOrthography.orthographyWithDominantScript_languageMap_(
            "Latn", {"Latn": [language]}
        )
    }
    return checker, language, NSTextCheckingTypeSpelling, options


class MacOSSpellChecker(QtCore.QObject):
    finished = QtCore.Signal(int, object)
    _checked = QtCore.Signal(int, bool)

    def __init__(self, parent=None, *, timeout_ms: int = 1500) -> None:
        super().__init__(parent)
        self._native = None
        self._generation = 0
        self._pending: tuple[int, str] | None = None
        self._closed = False
        self._cache: OrderedDict[str, tuple[str, ...]] = OrderedDict()
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self._timed_out)
        self._checked.connect(self._on_checked, QtCore.Qt.ConnectionType.QueuedConnection)

    def request(self, word: str) -> int:
        self.cancel()
        token = self._generation
        self._pending = (token, word.strip())
        self._timer.start()
        # Always return the token before delivering even a cached result.
        QtCore.QTimer.singleShot(0, lambda: self._begin(token))
        return token

    def cancel(self) -> None:
        self._generation += 1
        self._pending = None
        self._timer.stop()

    def close(self) -> None:
        self.cancel()
        self._closed = True
        self._cache.clear()
        self._native = None

    def _is_current(self, token: int) -> bool:
        return not self._closed and self._pending is not None and self._pending[0] == token

    def _begin(self, token: int) -> None:
        if not self._is_current(token):
            return
        word = self._pending[1]
        if sys.platform != "darwin" or len(word) > 80 or not _ENGLISH_INPUT.fullmatch(word):
            self._complete(token, [])
            return
        if word in self._cache:
            self._cache.move_to_end(word)
            self._complete(token, list(self._cache[word]))
            return
        try:
            if self._native is None:
                self._native = _native_checker()
            checker, _language, spelling_type, options = self._native
            receiver = weakref.ref(self)

            def completed(_sequence, results, _orthography, _word_count):
                # Cocoa invokes this on an arbitrary thread. Only plain Python
                # data crosses back to Qt; never call widgets from this block.
                target = receiver()
                if target is None:
                    return
                try:
                    misspelled = any(
                        result.resultType() & spelling_type and result.range().length > 0
                        for result in results
                    )
                    target._checked.emit(token, bool(misspelled))
                except Exception:
                    log.debug("spelling callback discarded", exc_info=True)

            checker.requestCheckingOfString_range_types_options_inSpellDocumentWithTag_completionHandler_(
                word, (0, len(word.encode("utf-16-le")) // 2), spelling_type, options, 0, completed
            )
        except Exception as exc:
            log.info("macOS spelling unavailable: %s", exc)
            self._complete(token, [])

    @QtCore.Slot(int, bool)
    def _on_checked(self, token: int, misspelled: bool) -> None:
        if not self._is_current(token):
            return
        word = self._pending[1]
        suggestions: list[str] = []
        try:
            # The checking service can report no error even when its guess API
            # offers a correction (perpective/accomodate on macOS). Only a
            # dictionary miss reaches this path; allow single-word suggestions.
            if misspelled or " " not in word:
                checker, language, _spelling_type, _options = self._native
                guesses = checker.guessesForWordRange_inString_language_inSpellDocumentWithTag_(
                    (0, len(word.encode("utf-16-le")) // 2), word, language, 0
                )
                seen = {word.casefold()}
                for guess in guesses or ():
                    candidate = str(guess).strip()
                    key = candidate.casefold()
                    if (
                        key in seen
                        or len(candidate) > 80
                        or not _ENGLISH_INPUT.fullmatch(candidate)
                    ):
                        continue
                    seen.add(key)
                    suggestions.append(candidate)
                    if len(suggestions) == MAX_CANDIDATES:
                        break
            self._cache[word] = tuple(suggestions)
            while len(self._cache) > 128:
                self._cache.popitem(last=False)
        except Exception as exc:
            log.info("macOS spelling suggestions unavailable: %s", exc)
        self._complete(token, suggestions)

    def _complete(self, token: int, suggestions: list[str]) -> None:
        if not self._is_current(token):
            return
        self._timer.stop()
        self._pending = None
        self.finished.emit(token, suggestions)

    @QtCore.Slot()
    def _timed_out(self) -> None:
        if self._pending is not None:
            log.info("macOS spelling timed out; continuing lookup queue")
            self._complete(self._pending[0], [])
