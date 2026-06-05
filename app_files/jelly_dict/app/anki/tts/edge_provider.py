"""edge-tts provider — invoked ONLY as a CLI subprocess.

edge-tts (the Python package) is GPL-3.0-or-later. We deliberately do NOT
``import edge_tts`` anywhere in jelly_dict; importing it would force GPL
on this codebase. Calling the standalone CLI binary as a separate process
is an "aggregate" per FSF guidance and does not propagate GPL.

Users who want this provider must install it themselves with e.g.
``pipx install edge-tts``. If the binary is not on PATH the provider is
reported as unavailable.

Note: edge-tts uses Microsoft's unofficial Edge Read-Aloud endpoint. This
is outside Microsoft's published API surface and may break at any time.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from app.anki.tts.base import ProviderInfo, TTSResult

if TYPE_CHECKING:
    from app.storage.settings_store import Settings

logger = logging.getLogger(__name__)


VOICES_EN: tuple[str, ...] = (
    "en-US-JennyNeural",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-GB-SoniaNeural",
)
VOICES_JA: tuple[str, ...] = (
    "ja-JP-NanamiNeural",
    "ja-JP-KeitaNeural",
)


class EdgeProvider:
    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            id="edge",
            display_name="edge-tts (외부 CLI)",
            available=cls.is_available(),
            voices_en=VOICES_EN,
            voices_ja=VOICES_JA,
            requires_credit=False,
            license_note="라이브러리: GPL-3.0 (별도 프로세스로만 호출 — jelly_dict 코드에 미포함)",
            usage_warning=(
                "MS 비공식 엔드포인트라 안정성 보장 X. "
                "사용하려면 `pipx install edge-tts` 별도 설치."
            ),
        )

    @classmethod
    def is_available(cls) -> bool:
        return shutil.which("edge-tts") is not None

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    def synthesize(
        self,
        text: str,
        *,
        language: str,
        voice: str,
        out_path: Path,
    ) -> TTSResult:
        if not text.strip():
            raise ValueError("empty text")
        # We must NOT log the text here verbatim if it could be sensitive;
        # word/example text is user content, no secrets, so it's fine.
        cmd = [
            "edge-tts",
            "--text", text,
            "--voice", voice,
            "--write-media", str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"edge-tts CLI failed: {exc.returncode}") from exc
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError("edge-tts produced no output")
        return TTSResult(
            path=out_path,
            engine_id="edge",
            voice=voice,
            requires_credit=False,
            credit_text="",
            license_note="edge-tts (GPL-3.0, 외부 CLI)",
        )
