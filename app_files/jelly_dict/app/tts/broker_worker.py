from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

from app.anki.tts.pipeline import TTSBatch, TTSPipeline
from app.core.models import VocabularyEntry
from app.core.settings import Settings
from app.tts.audio_service import pre_generate_entry_audio_with_pipeline


class _WorkerState:
    def __init__(self) -> None:
        self.pipelines: dict[tuple[object, ...], TTSPipeline] = {}

    def pipeline(self, settings: Settings) -> TTSPipeline:
        key = _pipeline_key(settings)
        pipeline = self.pipelines.get(key)
        if pipeline is None:
            pipeline = TTSPipeline(settings)
            self.pipelines[key] = pipeline
        return pipeline


def main() -> int:
    state = _WorkerState()
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _emit({"id": "", "ok": False, "error_type": "JSONDecodeError"})
            continue
        request_id = str(request.get("id") or "")
        if request.get("action") == "shutdown":
            _emit({"id": request_id, "ok": True})
            return 0
        try:
            with contextlib.redirect_stdout(sys.stderr):
                response = _handle(state, request)
        except Exception as exc:
            _emit(
                {
                    "id": request_id,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue
        response.update({"id": request_id, "ok": True})
        _emit(response)
    return 0


def _handle(state: _WorkerState, request: dict[str, Any]) -> dict[str, Any]:
    settings = Settings(**dict(request.get("settings") or {}))
    pipeline = state.pipeline(settings)
    action = request.get("action")
    if action == "synthesize_text":
        text = str(request.get("text") or "")
        language = str(request.get("language") or "en")
        batch = TTSBatch()
        path = pipeline.synthesize(text, language, batch)
        return {
            "path": str(path) if path is not None else "",
            "credits": sorted(batch.credits),
        }
    if action == "generate_entry":
        entry = VocabularyEntry.from_dict(dict(request.get("entry") or {}))
        generated = pre_generate_entry_audio_with_pipeline(
            entry,
            settings,
            pipeline,
        )
        return {"generated": generated}
    raise ValueError(f"unknown action: {action}")


def _pipeline_key(settings: Settings) -> tuple[object, ...]:
    return (
        settings.tts_engine_en,
        settings.tts_engine_ja,
        settings.tts_voice_en,
        settings.tts_voice_ja,
        settings.tts_bitrate,
        settings.tts_sample_rate,
        settings.excel_path_for("en"),
        settings.excel_path_for("ja"),
        settings.voicevox_url,
    )


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
