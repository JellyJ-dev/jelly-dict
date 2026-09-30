"""Secure storage for API keys and other secrets.

Keys are stored in the OS-level secret store (macOS Keychain via the
``keyring`` library). They are NEVER written to settings.json or any other
file inside the project tree. The only fallback is an environment variable
intended for tests/CI.

Design contract:
- ``set``/``get``/``delete`` are the only public surface.
- The returned secret is held in memory only by the caller; this module
  never logs or repr's the value.
- A ``key_set`` predicate allows the UI to show an on/off indicator without
  reading the value back.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SERVICE_NAME = "jelly_dict"

# Map of secret name -> environment variable used as a fallback
# (intended for tests/CI; never persisted).
_ENV_FALLBACK = {
    "google_vision_api_key": "JELLY_DICT_GOOGLE_VISION_API_KEY",
}


def _keyring():
    """Lazy import: keyring is an optional but recommended dep.

    If keyring is unavailable (e.g. in a minimal test env), we fall back to
    env-var-only mode so the rest of the app still works.
    """
    try:
        import keyring  # type: ignore

        return keyring
    except ImportError:  # pragma: no cover
        logger.warning("keyring not installed; secrets will only be read from env vars")
        return None


def set(name: str, value: str) -> None:
    """Store ``value`` for ``name`` in the OS keychain."""
    if not value:
        delete(name)
        return
    kr = _keyring()
    if kr is None:
        raise RuntimeError("keyring is not installed; install `keyring>=24` to save API keys.")
    kr.set_password(SERVICE_NAME, name, value)


def get(name: str) -> Optional[str]:
    """Return the secret for ``name`` or ``None`` if not set."""
    env_name = _ENV_FALLBACK.get(name)
    if env_name:
        from_env = os.environ.get(env_name)
        if from_env:
            return from_env
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE_NAME, name)
    except Exception as exc:  # keyring backends raise various errors
        logger.warning("keyring read failed for %s: %s", name, type(exc).__name__)
        return None


def delete(name: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE_NAME, name)
    except Exception:
        # keyring raises PasswordDeleteError when the entry doesn't exist;
        # treat absence as success.
        pass


def is_set(name: str) -> bool:
    return bool(get(name))


def mask(value: Optional[str]) -> str:
    """Return a UI-safe masked representation of a secret."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "…" + "•" * 4
