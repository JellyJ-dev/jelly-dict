"""Kokoro local TTS provider.

Apache-2.0 model + MIT-licensed Python wrapper. No credit obligation.
Requires the optional dependency group: see requirements-tts.txt.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.anki.tts.base import ProviderInfo, TTSResult
from app.anki.tts.transcode import wav_to_mp3

if TYPE_CHECKING:
    from app.storage.settings_store import Settings

KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
VOICES_EN: tuple[str, ...] = (
    "af_heart",
    "af_bella",
    "af_nicole",
    "am_adam",
    "am_michael",
    "bf_emma",
)
VOICES_JA: tuple[str, ...] = (
    "jf_alpha",
    "jf_gongitsune",
    "jm_kumo",
)
KOKORO_MODEL_FILES: tuple[str, ...] = (
    "config.json",
    "kokoro-v1_0.pth",
)
KOKORO_VOICE_FILES: tuple[str, ...] = tuple(
    f"voices/{voice}.pt" for voice in (*VOICES_EN, *VOICES_JA)
)
KOKORO_REQUIRED_FILES: tuple[str, ...] = (
    *KOKORO_MODEL_FILES,
    *KOKORO_VOICE_FILES,
)


class KokoroOfflineAssetError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        language: str,
        asset: str,
    ) -> None:
        self.language = language
        self.asset = asset
        super().__init__(message)


class KokoroProvider:
    @classmethod
    def info(cls) -> ProviderInfo:
        return ProviderInfo(
            id="kokoro",
            display_name="Kokoro (로컬)",
            available=cls.is_available(),
            voices_en=VOICES_EN,
            voices_ja=VOICES_JA,
            requires_credit=False,
            license_note="Apache-2.0 / MIT — 자유 사용 가능",
            usage_warning="",
        )

    @classmethod
    def is_available(cls) -> bool:
        return cls.is_available_for("en") or cls.is_available_for("ja")

    @classmethod
    def is_available_for(cls, language: str) -> bool:
        if not cls.runtime_available_for(language):
            return False
        voices = VOICES_JA if language == "ja" else VOICES_EN
        return any(cls.is_voice_available(voice, language) for voice in voices)

    @classmethod
    def runtime_available_for(cls, language: str) -> bool:
        if language not in {"en", "ja"}:
            return False
        if not _common_runtime_available() or _local_model_files() is None:
            return False
        return _japanese_runtime_available() if language == "ja" else _english_runtime_available()

    @classmethod
    def is_voice_available(cls, voice: str, language: str) -> bool:
        allowed = VOICES_JA if language == "ja" else VOICES_EN if language == "en" else ()
        return voice in allowed and _local_voice_path(voice) is not None

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._model = None
        self._pipeline_en = None
        self._pipeline_ja = None

    def _pipeline_for(self, language: str):
        from kokoro import KPipeline  # type: ignore

        if language == "ja":
            _require_local_japanese_g2p()
            if self._pipeline_ja is None:
                try:
                    self._pipeline_ja = KPipeline(
                        lang_code="j",
                        repo_id=KOKORO_REPO_ID,
                        model=self._model_for_kokoro(),
                    )
                except ModuleNotFoundError as exc:
                    if "pyopenjtalk" in str(exc) or "misaki" in str(exc):
                        raise RuntimeError(
                            "일본어 음소 모듈이 누락됐습니다. 설정의 Kokoro 🗑로 "
                            "한 번 삭제 후 다시 설치하거나 "
                            "`pip install 'misaki[ja]'`을 실행하세요."
                        ) from exc
                    raise
                except RuntimeError as exc:
                    msg = str(exc)
                    if "MeCab" in msg or "mecabrc" in msg or "dicdir" in msg or "unidic" in msg:
                        raise RuntimeError(
                            "일본어 형태소 사전(unidic)이 다운로드되지 않았습니다. "
                            "설정의 Kokoro 🗑로 삭제 후 다시 설치하거나, "
                            "터미널에서 `python -m unidic download`를 실행하세요."
                        ) from exc
                    raise
            return self._pipeline_ja
        if self._pipeline_en is None:
            _require_local_english_g2p()
            self._pipeline_en = KPipeline(
                lang_code="a",
                repo_id=KOKORO_REPO_ID,
                model=self._model_for_kokoro(),
            )
        return self._pipeline_en

    def _model_for_kokoro(self):
        if self._model is not None:
            return self._model
        local = _local_model_files()
        if local is None:
            raise RuntimeError(
                "Kokoro 로컬 모델 캐시가 없습니다. 설정에서 Kokoro 설치를 실행하세요."
            )
        try:
            import torch  # type: ignore
            from kokoro.model import KModel  # type: ignore

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = (
                KModel(
                    repo_id=KOKORO_REPO_ID,
                    config=str(local[0]),
                    model=str(local[1]),
                )
                .to(device)
                .eval()
            )
            return self._model
        except Exception as exc:
            raise RuntimeError(f"Kokoro 로컬 모델 로드 실패: {exc}") from exc

    def synthesize(
        self,
        text: str,
        *,
        language: str,
        voice: str,
        out_path: Path,
    ) -> TTSResult:
        voice_path = _require_local_voice(voice, language)
        pipeline = self._pipeline_for(language)
        import soundfile as sf  # type: ignore

        voice_ref = str(voice_path)
        # KPipeline yields (graphemes, phonemes, audio) per chunk.
        chunks: list = []
        for _g, _p, audio in pipeline(text, voice=voice_ref):
            chunks.append(audio)
        if not chunks:
            raise RuntimeError("Kokoro produced no audio")

        # Concatenate if multiple chunks.
        if len(chunks) == 1:
            audio = chunks[0]
        else:
            import numpy as np  # type: ignore

            audio = np.concatenate(chunks)

        # Kokoro samples at 24kHz. Write WAV first, then ffmpeg → mp3.
        wav_path = out_path.with_suffix(".wav")
        sf.write(str(wav_path), audio, 24000)
        result_path = wav_to_mp3(wav_path, out_path, self._settings) or out_path

        return TTSResult(
            path=result_path,
            engine_id="kokoro",
            voice=voice,
            requires_credit=False,
            credit_text="",
            license_note="Kokoro (Apache-2.0)",
        )


def _kokoro_cache_root() -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"


def _require_local_english_g2p() -> None:
    import importlib.util

    if importlib.util.find_spec("spacy") is None:
        raise RuntimeError(
            "Kokoro 영어 TTS에 필요한 spaCy가 설치돼 있지 않습니다. "
            "설정에서 Kokoro를 다시 설치하세요."
        )
    import spacy.util  # type: ignore

    if not spacy.util.is_package("en_core_web_sm"):
        raise RuntimeError(
            "Kokoro 영어 G2P 모델(en_core_web_sm)이 설치돼 있지 않습니다. "
            "설정에서 Kokoro를 다시 설치하세요."
        )


def _require_local_japanese_g2p() -> None:
    if _japanese_runtime_available():
        return
    raise KokoroOfflineAssetError(
        "Kokoro 일본어 TTS에 필요한 로컬 음소 모듈 또는 unidic 사전이 "
        "없습니다. 설정에서 Kokoro를 다시 설치하세요.",
        language="ja",
        asset="japanese-g2p",
    )


def _require_local_voice(voice: str, language: str) -> Path:
    allowed = VOICES_JA if language == "ja" else VOICES_EN if language == "en" else ()
    if voice not in allowed:
        raise KokoroOfflineAssetError(
            f"Kokoro {language} 음성은 로컬 manifest에 없습니다: {voice}",
            language=language,
            asset=f"voice:{voice}",
        )
    path = _local_voice_path(voice)
    if path is None:
        raise KokoroOfflineAssetError(
            f"Kokoro 로컬 음성 파일이 없습니다: {voice}",
            language=language,
            asset=f"voice:{voice}",
        )
    return path


def _common_runtime_available() -> bool:
    return _modules_available("kokoro", "soundfile")


def _english_runtime_available() -> bool:
    return _modules_available("spacy", "en_core_web_sm")


def _japanese_runtime_available() -> bool:
    if not _modules_available("misaki", "pyopenjtalk", "fugashi", "unidic"):
        return False
    import importlib.util

    spec = importlib.util.find_spec("unidic")
    locations = (
        tuple(getattr(spec, "submodule_search_locations", ()) or ()) if spec is not None else ()
    )
    return any((Path(location) / "dicdir" / "mecabrc").exists() for location in locations)


def _modules_available(*names: str) -> bool:
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in names)


def _local_snapshot_dir() -> Path | None:
    root = _kokoro_cache_root()
    ref = root / "refs" / "main"
    if ref.exists():
        try:
            snapshot = root / "snapshots" / ref.read_text(encoding="utf-8").strip()
            if snapshot.exists():
                return snapshot
        except OSError:
            pass
    snapshots = root / "snapshots"
    if not snapshots.exists():
        return None
    candidates = [p for p in snapshots.iterdir() if p.is_dir()]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _local_model_files() -> tuple[Path, Path] | None:
    snapshot = _local_snapshot_dir()
    if snapshot is None:
        return None
    config = snapshot / "config.json"
    model = snapshot / "kokoro-v1_0.pth"
    if config.exists() and model.exists():
        return config, model
    return None


def _local_voice_path(voice: str) -> Path | None:
    snapshot = _local_snapshot_dir()
    if snapshot is None:
        return None
    path = snapshot / "voices" / f"{voice}.pt"
    return path if path.exists() else None
