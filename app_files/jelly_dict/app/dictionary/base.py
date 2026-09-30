from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.domain import LookupResult
from app.core.models import Language


@runtime_checkable
class DictionaryProvider(Protocol):
    def lookup(self, word: str, language: Language) -> LookupResult: ...

    def supports(self, language: Language) -> bool: ...
