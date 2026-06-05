from __future__ import annotations

from datetime import datetime, timezone


def utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
