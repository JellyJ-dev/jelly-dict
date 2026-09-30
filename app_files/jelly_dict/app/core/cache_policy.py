from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.core.models import Language, VocabularyEntry

CACHE_DATABASE_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CacheSchemaContract:
    provider_id: str
    provider_schema_version: int
    parser_id: str
    parser_schema_version: int


_LOOKUP_CONTRACTS: dict[tuple[str, Language], CacheSchemaContract] = {
    ("naver_crawler", "en"): CacheSchemaContract("naver_crawler", 1, "naver_en", 5),
    ("naver_crawler", "ja"): CacheSchemaContract("naver_crawler", 1, "naver_ja", 1),
    ("manual", "en"): CacheSchemaContract("manual", 1, "manual", 1),
    ("manual", "ja"): CacheSchemaContract("manual", 1, "manual", 1),
}

_CURRENT_CONTRACTS: dict[tuple[str, str, Language], CacheSchemaContract] = {
    (contract.provider_id, contract.parser_id, language): contract
    for (_, language), contract in _LOOKUP_CONTRACTS.items()
}
_CURRENT_CONTRACTS[("naver_crawler", "naver_open", "en")] = _LOOKUP_CONTRACTS[
    ("naver_crawler", "en")
]
for _language in ("en", "ja"):
    _CURRENT_CONTRACTS[("naver_crawler", "naver_api", _language)] = CacheSchemaContract(
        "naver_crawler", 1, "naver_api", 1
    )

_VERSIONED_PROVIDER_IDS = frozenset(
    contract.provider_id for contract in _CURRENT_CONTRACTS.values()
)

_SOURCE_PROVIDERS: dict[str, str] = {
    "naver_en": "naver_crawler",
    "naver_open": "naver_crawler",
    "naver_ja": "naver_crawler",
    "naver_api": "naver_crawler",
    "manual": "manual",
}


def cache_spelling_matches(query: str, entry: VocabularyEntry) -> bool:
    """Avoid returning a lowercase homograph for an acronym, or the reverse."""
    if entry.language != "en" or entry.source_provider not in {
        "naver_en",
        "naver_open",
        "naver_api",
    }:
        return True
    query = unicodedata.normalize("NFKC", query).strip()
    canonical = unicodedata.normalize("NFKC", entry.word).strip()
    if re.fullmatch(r"[A-Z]{2,8}", query) or re.fullmatch(r"[A-Z]{2,8}", canonical):
        return query == canonical
    return True


def lookup_cache_contract(
    provider_id: str,
    language: Language,
) -> CacheSchemaContract:
    normalized = (provider_id or "unknown").strip().lower() or "unknown"
    configured = _LOOKUP_CONTRACTS.get((normalized, language))
    if configured is not None:
        return configured
    return CacheSchemaContract(
        normalized,
        1,
        f"{normalized}:{language}",
        1,
    )


def entry_cache_contract(
    entry: VocabularyEntry,
    requested_provider_id: str | None = None,
) -> CacheSchemaContract:
    if requested_provider_id:
        return lookup_cache_contract(requested_provider_id, entry.language)
    source = (entry.source_provider or "unknown").strip().lower() or "unknown"
    provider_id = _SOURCE_PROVIDERS.get(source, source)
    configured = _CURRENT_CONTRACTS.get((provider_id, source, entry.language))
    if configured is not None:
        return configured
    return CacheSchemaContract(provider_id, 1, source, 1)


def cache_contract_is_current(
    *,
    provider_id: str,
    provider_schema_version: int,
    parser_id: str,
    parser_schema_version: int,
    language: Language,
) -> bool:
    configured = _CURRENT_CONTRACTS.get((provider_id, parser_id, language))
    if configured is not None:
        expected = configured
    elif provider_id in _VERSIONED_PROVIDER_IDS:
        return False
    else:
        expected = CacheSchemaContract(provider_id, 1, parser_id, 1)
    return (
        provider_schema_version == expected.provider_schema_version
        and parser_schema_version == expected.parser_schema_version
    )


def cache_contract_matches_lookup(
    contract: CacheSchemaContract,
    provider_id: str,
    language: Language,
) -> bool:
    return contract == lookup_cache_contract(provider_id, language)
