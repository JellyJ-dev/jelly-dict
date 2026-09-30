"""Owned, concurrent-safe audio cache for generated TTS media."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from app.core import config

AUDIO_CACHE_SCHEMA_VERSION = 1
MANIFEST_VERSION = 2
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_AGE_SECONDS = 90 * 24 * 60 * 60

_NAME_SAFE = re.compile(r"[^A-Za-z0-9_\-]+")
_OWNED_FILENAME = re.compile(
    r"^(?:en|ja)_[A-Za-z0-9_-]+_[A-Za-z0-9_-]+_[0-9a-f]{12,64}\.(?:mp3|wav)$"
)
_MANIFEST_NAME = ".jelly-tts-cache.json"
_MANIFEST_LOCK_NAME = ".jelly-tts-cache.lock"
_KEY_LOCK_DIR = ".jelly-tts-locks"
_TOUCH_INTERVAL_SECONDS = 60.0
_PRUNE_INTERVAL_SECONDS = 60 * 60.0

_PROVIDER_VERSIONS = {
    "kokoro": "provider-1",
    "voicevox": "provider-1",
    "edge": "provider-1",
}
_MODEL_VERSIONS = {
    "kokoro": "Kokoro-82M-v1.0",
    "voicevox": "local-engine-api-v1",
    "edge": "edge-tts-cli-v1",
}

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
_MANIFEST_THREAD_LOCK = threading.RLock()
_PRUNE_GUARD = threading.Lock()
_LAST_PRUNE: dict[str, float] = {}
_PIN_GUARD = threading.Lock()
_PINNED: dict[tuple[str, str], int] = {}


@dataclass(frozen=True)
class AudioCacheKey:
    language: str
    provider: str
    voice: str
    text_hash: str
    bitrate: str
    sample_rate: str
    provider_version: str
    model_version: str
    schema_version: int = AUDIO_CACHE_SCHEMA_VERSION

    @classmethod
    def for_text(
        cls,
        language: str,
        provider: str,
        voice: str,
        text: str,
        *,
        bitrate: str = "",
        sample_rate: int | str | None = None,
        provider_version: str | None = None,
        model_version: str | None = None,
        schema_version: int = AUDIO_CACHE_SCHEMA_VERSION,
    ) -> "AudioCacheKey":
        provider_id = str(provider or "none")
        return cls(
            language=str(language or "en"),
            provider=provider_id,
            voice=str(voice or "default"),
            text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            bitrate=str(bitrate or ""),
            sample_rate=str(sample_rate or ""),
            provider_version=str(
                provider_version or _PROVIDER_VERSIONS.get(provider_id, "provider-1")
            ),
            model_version=str(model_version or _MODEL_VERSIONS.get(provider_id, "model-1")),
            schema_version=int(schema_version),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "provider": self.provider,
            "voice": self.voice,
            "text_hash": self.text_hash,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "provider_version": self.provider_version,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
        }

    @property
    def id(self) -> str:
        encoded = json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def stem(self) -> str:
        language = _safe_component(self.language, "en", limit=8)
        provider = _safe_component(self.provider, "none", limit=40)
        voice = _safe_component(self.voice, "default", limit=40)
        return f"{language}_{provider}_{voice}_{self.id[:20]}"


@dataclass(frozen=True)
class AudioCacheResult:
    path: Path
    created: bool


class AudioLease:
    """Shared file-lock lease preventing retention from deleting one entry."""

    def __init__(self, base: Path, entry_id: str) -> None:
        self._base = base
        self._entry_id = entry_id
        self._file = None
        self._closed = False
        lock_dir = base / _KEY_LOCK_DIR
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (lock_dir / f"{entry_id}.lock").open("a+b")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        except BaseException:
            lock_file.close()
            raise
        self._file = lock_file
        marker = (str(base.resolve()), entry_id)
        with _PIN_GUARD:
            _PINNED[marker] = _PINNED.get(marker, 0) + 1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        marker = (str(self._base.resolve()), self._entry_id)
        with _PIN_GUARD:
            count = _PINNED.get(marker, 0)
            if count <= 1:
                _PINNED.pop(marker, None)
            else:
                _PINNED[marker] = count - 1
        if self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None

    def __enter__(self) -> "AudioLease":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - defensive fallback
        self.close()


class AudioCache:
    def __init__(self, base: Path) -> None:
        self.base = Path(base).expanduser()
        self.base.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: AudioCacheKey, *, suffix: str = ".mp3") -> Path:
        suffix = suffix if suffix in {".mp3", ".wav"} else ".mp3"
        return self.base / f"{key.stem}{suffix}"

    def lookup(self, key: AudioCacheKey, *, touch: bool = True) -> Path | None:
        now = time.time()
        with _manifest_lock(self.base):
            entries = _read_manifest_entries(self.base)
            entry = entries.get(key.id)
            path = _entry_path(self.base, entry)
            if path is not None and is_valid_audio_file(path):
                if touch and now - _entry_last_used(entry) >= _TOUCH_INTERVAL_SECONDS:
                    updated = _manifest_entry(key, path, now=now)
                    updated["created"] = entry.get("created", now)
                    entries[key.id] = updated
                    _write_manifest_entries(self.base, entries)
                return path

        # Adopt a deterministic file created before its manifest commit.
        for suffix in (".mp3", ".wav"):
            path = self.path_for(key, suffix=suffix)
            if is_valid_audio_file(path) and audio_file_format(path) == suffix[1:]:
                self.register(key, path, now=now)
                return path
        return None

    def get_or_create(
        self,
        key: AudioCacheKey,
        producer: Callable[[Path], Path],
    ) -> AudioCacheResult:
        cached = self.lookup(key)
        if cached is not None:
            return AudioCacheResult(cached, False)

        with _key_lock(self.base, key.id, blocking=True) as acquired:
            if not acquired:  # pragma: no cover - blocking acquisition
                raise RuntimeError("audio cache key lock unavailable")
            cached = self.lookup(key)
            if cached is not None:
                return AudioCacheResult(cached, False)

            token = uuid.uuid4().hex
            prefix = f".{key.stem}.{token}.tmp"
            temp_mp3 = self.base / f"{prefix}.mp3"
            temp_wav = self.base / f"{prefix}.wav"
            try:
                produced = Path(producer(temp_mp3)).expanduser()
                if produced.parent != self.base or produced not in {temp_mp3, temp_wav}:
                    raise RuntimeError("TTS provider returned an unmanaged temp path")
                audio_format = audio_file_format(produced)
                if audio_format not in {"mp3", "wav"}:
                    raise RuntimeError("TTS provider produced invalid audio")
                final = self.path_for(key, suffix=f".{audio_format}")
                produced.replace(final)
                _fsync_file_and_directory(final)
                self.register(key, final)
                self._maybe_prune()
                return AudioCacheResult(final, True)
            finally:
                # A failed request may only remove files bearing its UUID.
                for temp in (temp_mp3, temp_wav):
                    try:
                        temp.unlink(missing_ok=True)
                    except OSError:
                        pass

    def register(
        self,
        key: AudioCacheKey,
        path: Path,
        *,
        now: float | None = None,
    ) -> bool:
        path = Path(path).expanduser()
        if path.parent != self.base or not is_owned_cache_filename(path.name):
            return False
        audio_format = audio_file_format(path)
        if audio_format is None or path.suffix != f".{audio_format}":
            return False
        with _manifest_lock(self.base):
            entries = _read_manifest_entries(self.base)
            for entry_id, entry in tuple(entries.items()):
                if entry_id != key.id and entry.get("filename") == path.name:
                    entries.pop(entry_id, None)
            updated = _manifest_entry(key, path, now=now)
            previous = entries.get(key.id)
            if isinstance(previous, dict):
                updated["created"] = previous.get("created", updated["created"])
            entries[key.id] = updated
            _write_manifest_entries(self.base, entries)
        return True

    def clear(self) -> int:
        with _manifest_lock(self.base):
            entry_ids = tuple(_read_manifest_entries(self.base))
        removed = 0
        for entry_id in entry_ids:
            if self._delete_entry(entry_id):
                removed += 1
        return removed

    def prune(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        now: float | None = None,
    ) -> int:
        now = time.time() if now is None else float(now)
        with _manifest_lock(self.base):
            entries = _read_manifest_entries(self.base)

        records: list[tuple[str, float, int]] = []
        for entry_id, entry in entries.items():
            path = _entry_path(self.base, entry)
            if path is None:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            records.append((entry_id, _entry_last_used(entry), size))

        expired = {
            entry_id
            for entry_id, last_used, _size in records
            if max_age_seconds >= 0 and now - last_used > max_age_seconds
        }
        projected = sum(size for _entry_id, _last_used, size in records)
        projected -= sum(size for entry_id, _last_used, size in records if entry_id in expired)
        selected = set(expired)
        if max_bytes >= 0 and projected > max_bytes:
            for entry_id, _last_used, size in sorted(records, key=lambda row: row[1]):
                if entry_id in selected:
                    continue
                selected.add(entry_id)
                projected -= size
                if projected <= max_bytes:
                    break

        removed = 0
        for entry_id in selected:
            if self._delete_entry(entry_id):
                removed += 1
        return removed

    def _delete_entry(self, entry_id: str) -> bool:
        # Non-blocking locks preserve files currently being generated/readied.
        marker = (str(self.base.resolve()), entry_id)
        with _PIN_GUARD:
            if _PINNED.get(marker, 0) > 0:
                return False
        with _key_lock(self.base, entry_id, blocking=False) as acquired:
            if not acquired:
                return False
            with _manifest_lock(self.base):
                entries = _read_manifest_entries(self.base)
                entry = entries.get(entry_id)
                if entry is None:
                    return False
                path = _entry_path(self.base, entry)
                existed = path is not None and path.exists()
                if path is not None:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        return False
                entries.pop(entry_id, None)
                _write_manifest_entries(self.base, entries)
                return existed

    def _maybe_prune(self) -> None:
        marker = str(self.base.resolve())
        now = time.monotonic()
        with _PRUNE_GUARD:
            previous = _LAST_PRUNE.get(marker, 0.0)
            if now - previous < _PRUNE_INTERVAL_SECONDS:
                return
            _LAST_PRUNE[marker] = now
        self.prune()


def cache_key(
    language: str,
    engine: str,
    voice: str,
    text: str,
    *,
    bitrate: str = "",
    sample_rate: int | str | None = None,
    provider_version: str | None = None,
    model_version: str | None = None,
    schema_version: int = AUDIO_CACHE_SCHEMA_VERSION,
) -> AudioCacheKey:
    return AudioCacheKey.for_text(
        language,
        engine,
        voice,
        text,
        bitrate=bitrate,
        sample_rate=sample_rate,
        provider_version=provider_version,
        model_version=model_version,
        schema_version=schema_version,
    )


def cache_path(
    language: str,
    engine: str,
    voice: str,
    text: str,
    *,
    bitrate: str = "",
    sample_rate: int | str | None = None,
    cache_dir: Path | None = None,
    provider_version: str | None = None,
    model_version: str | None = None,
    schema_version: int = AUDIO_CACHE_SCHEMA_VERSION,
) -> Path:
    key = cache_key(
        language,
        engine,
        voice,
        text,
        bitrate=bitrate,
        sample_rate=sample_rate,
        provider_version=provider_version,
        model_version=model_version,
        schema_version=schema_version,
    )
    return AudioCache(cache_dir or config.tts_cache_dir()).path_for(key)


def cached_path(
    language: str,
    engine: str,
    voice: str,
    text: str,
    *,
    bitrate: str = "",
    sample_rate: int | str | None = None,
    cache_dir: Path | None = None,
    provider_version: str | None = None,
    model_version: str | None = None,
    schema_version: int = AUDIO_CACHE_SCHEMA_VERSION,
) -> Path | None:
    key = cache_key(
        language,
        engine,
        voice,
        text,
        bitrate=bitrate,
        sample_rate=sample_rate,
        provider_version=provider_version,
        model_version=model_version,
        schema_version=schema_version,
    )
    return AudioCache(cache_dir or config.tts_cache_dir()).lookup(key)


def wordbook_audio_dir(settings, language: str) -> Path:
    try:
        raw_path = settings.excel_path_for(language)
    except Exception:
        return config.tts_cache_dir()
    if not str(raw_path or "").strip():
        return config.tts_cache_dir()
    excel_path = Path(raw_path).expanduser()
    base = excel_path.parent if excel_path.name else excel_path
    path = base / "mp3"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audio_file_format(path: Path) -> str | None:
    try:
        if not path.exists() or path.stat().st_size < 16:
            return None
        with path.open("rb") as stream:
            header = stream.read(4096)
    except OSError:
        return None
    if _looks_like_mp3(header):
        return "mp3"
    if _looks_like_wav(header):
        return "wav"
    return None


def is_valid_audio_file(path: Path) -> bool:
    return audio_file_format(path) is not None


def is_owned_cache_filename(name: str) -> bool:
    return bool(_OWNED_FILENAME.fullmatch(name or ""))


def register_owned_audio(path: Path) -> bool:
    """Compatibility registration for callers without a structured key."""
    path = Path(path).expanduser()
    if not is_owned_cache_filename(path.name) or not is_valid_audio_file(path):
        return False
    audio_format = audio_file_format(path)
    if audio_format is None or path.suffix != f".{audio_format}":
        return False
    entry_id = "legacy-" + hashlib.sha256(path.name.encode("utf-8")).hexdigest()
    with _manifest_lock(path.parent):
        entries = _read_manifest_entries(path.parent)
        entries = {
            candidate_id: candidate
            for candidate_id, candidate in entries.items()
            if candidate.get("filename") != path.name
        }
        existing = entries.get(entry_id, {})
        entries[entry_id] = {
            "filename": path.name,
            "last_used": time.time(),
            "created": float(existing.get("created") or time.time()),
            "size": path.stat().st_size,
            "key": None,
        }
        _write_manifest_entries(path.parent, entries)
    return True


def acquire_audio_lease(path: Path) -> AudioLease | None:
    path = Path(path).expanduser()
    if not path.exists():
        return None
    with _manifest_lock(path.parent):
        entries = _read_manifest_entries(path.parent)
        entry_id = next(
            (
                candidate_id
                for candidate_id, entry in entries.items()
                if entry.get("filename") == path.name
            ),
            None,
        )
    if entry_id is None:
        return None
    return AudioLease(path.parent, entry_id)


def unregister_owned_audio(path: Path) -> None:
    path = Path(path).expanduser()
    if not is_owned_cache_filename(path.name):
        return
    with _manifest_lock(path.parent):
        entries = _read_manifest_entries(path.parent)
        filtered = {
            entry_id: entry
            for entry_id, entry in entries.items()
            if entry.get("filename") != path.name
        }
        if len(filtered) != len(entries):
            _write_manifest_entries(path.parent, filtered)


def clear_cache(
    cache_dirs: list[Path] | tuple[Path, ...] | set[Path] | None = None,
) -> int:
    bases = list(cache_dirs) if cache_dirs is not None else [config.tts_cache_dir()]
    count = 0
    seen: set[Path] = set()
    for raw_base in bases:
        try:
            base = Path(raw_base).expanduser()
        except TypeError:
            continue
        if base in seen or not base.exists():
            continue
        seen.add(base)
        count += AudioCache(base).clear()
    return count


def prune_cache(
    cache_dirs: list[Path] | tuple[Path, ...] | set[Path] | None = None,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> int:
    bases = list(cache_dirs) if cache_dirs is not None else [config.tts_cache_dir()]
    count = 0
    seen: set[Path] = set()
    for raw_base in bases:
        base = Path(raw_base).expanduser()
        if base in seen or not base.exists():
            continue
        seen.add(base)
        count += AudioCache(base).prune(
            max_bytes=max_bytes,
            max_age_seconds=max_age_seconds,
            now=now,
        )
    return count


def _manifest_entry(
    key: AudioCacheKey,
    path: Path,
    *,
    now: float | None = None,
) -> dict[str, object]:
    timestamp = time.time() if now is None else float(now)
    return {
        "filename": path.name,
        "last_used": timestamp,
        "created": timestamp,
        "size": path.stat().st_size,
        "key": key.as_dict(),
    }


def _entry_path(base: Path, entry: object) -> Path | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("filename")
    if not isinstance(name, str) or Path(name).name != name:
        return None
    if not is_owned_cache_filename(name):
        return None
    return base / name


def _entry_last_used(entry: object) -> float:
    if not isinstance(entry, dict):
        return 0.0
    try:
        return float(entry.get("last_used") or entry.get("created") or 0.0)
    except (TypeError, ValueError):
        return 0.0


@contextmanager
def _manifest_lock(base: Path) -> Iterator[None]:
    base.mkdir(parents=True, exist_ok=True)
    with _MANIFEST_THREAD_LOCK:
        with (base / _MANIFEST_LOCK_NAME).open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _key_lock(base: Path, entry_id: str, *, blocking: bool) -> Iterator[bool]:
    base.mkdir(parents=True, exist_ok=True)
    registry_key = f"{base.resolve()}\0{entry_id}"
    with _THREAD_LOCKS_GUARD:
        lock, refs = _THREAD_LOCKS.get(registry_key, (threading.Lock(), 0))
        _THREAD_LOCKS[registry_key] = (lock, refs + 1)
    acquired_thread = lock.acquire(blocking=blocking)
    if not acquired_thread:
        _release_registry_ref(registry_key)
        yield False
        return
    lock_file = None
    acquired_file = False
    try:
        lock_dir = base / _KEY_LOCK_DIR
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (lock_dir / f"{entry_id}.lock").open("a+b")
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(lock_file.fileno(), flags)
            acquired_file = True
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        if acquired_file and lock_file is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        if lock_file is not None:
            lock_file.close()
        lock.release()
        _release_registry_ref(registry_key)


def _release_registry_ref(registry_key: str) -> None:
    with _THREAD_LOCKS_GUARD:
        item = _THREAD_LOCKS.get(registry_key)
        if item is None:
            return
        lock, refs = item
        if refs <= 1:
            _THREAD_LOCKS.pop(registry_key, None)
        else:
            _THREAD_LOCKS[registry_key] = (lock, refs - 1)


def _read_manifest_entries(base: Path) -> dict[str, dict[str, object]]:
    path = base / _MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("version") == MANIFEST_VERSION:
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, dict):
            return {}
        return {
            str(entry_id): dict(entry)
            for entry_id, entry in raw_entries.items()
            if isinstance(entry_id, str) and isinstance(entry, dict)
        }
    if payload.get("version") == 1 and isinstance(payload.get("files"), list):
        entries: dict[str, dict[str, object]] = {}
        for name in payload["files"]:
            if not isinstance(name, str) or not is_owned_cache_filename(name):
                continue
            entry_id = "legacy-" + hashlib.sha256(name.encode("utf-8")).hexdigest()
            path = base / name
            try:
                stat = path.stat()
                modified = stat.st_mtime
                size = stat.st_size
            except OSError:
                modified = 0.0
                size = 0
            entries[entry_id] = {
                "filename": name,
                "last_used": modified,
                "created": modified,
                "size": size,
                "key": None,
            }
        return entries
    return {}


def _write_manifest_entries(
    base: Path,
    entries: dict[str, dict[str, object]],
) -> None:
    payload = (
        json.dumps(
            {"version": MANIFEST_VERSION, "entries": entries},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=base,
            prefix=f".{_MANIFEST_NAME}.",
            suffix=".tmp",
            encoding="utf-8",
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_name = temp_file.name
        Path(temp_name).replace(base / _MANIFEST_NAME)
        _fsync_directory(base)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_file_and_directory(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    except OSError:
        pass
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _looks_like_mp3(header: bytes) -> bool:
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True
    if not header.startswith(b"ID3") or len(header) < 12:
        return False
    tag_size = _id3_synchsafe_size(header[6:10]) if len(header) >= 10 else None
    search_start = 10 + (tag_size or 0)
    window = header[search_start:] or header[10:]
    return _contains_mp3_frame_sync(window)


def _id3_synchsafe_size(raw: bytes) -> int | None:
    if len(raw) != 4 or any(byte & 0x80 for byte in raw):
        return None
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def _contains_mp3_frame_sync(data: bytes) -> bool:
    for index in range(max(0, len(data) - 1)):
        if data[index] == 0xFF and (data[index + 1] & 0xE0) == 0xE0:
            return True
    return False


def _looks_like_wav(header: bytes) -> bool:
    if not (header.startswith(b"RIFF") and header[8:12] == b"WAVE"):
        return False
    return b"fmt " in header[12:] and b"data" in header[12:]


def _safe_component(value: str, fallback: str, *, limit: int) -> str:
    normalized = _NAME_SAFE.sub("-", value or fallback).strip("-")
    return (normalized or fallback)[:limit]


__all__ = [
    "AUDIO_CACHE_SCHEMA_VERSION",
    "AudioCache",
    "AudioCacheKey",
    "AudioCacheResult",
    "AudioLease",
    "DEFAULT_MAX_AGE_SECONDS",
    "DEFAULT_MAX_BYTES",
    "audio_file_format",
    "acquire_audio_lease",
    "cache_key",
    "cache_path",
    "cached_path",
    "clear_cache",
    "is_owned_cache_filename",
    "is_valid_audio_file",
    "prune_cache",
    "register_owned_audio",
    "unregister_owned_audio",
    "wordbook_audio_dir",
]
