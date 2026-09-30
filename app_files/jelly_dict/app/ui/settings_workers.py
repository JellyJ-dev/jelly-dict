from __future__ import annotations

from PySide6 import QtCore

from app.storage import secret_store


class _SettingsStatusWorker(QtCore.QObject):
    finished = QtCore.Signal(object)

    @QtCore.Slot()
    def run(self) -> None:
        status = {
            "gv_key_set": False,
            "kokoro_available": False,
            "edge_available": False,
            "brew_available": False,
            "kokoro_cache_mb": 0.0,
        }
        try:
            status["gv_key_set"] = secret_store.is_set("google_vision_api_key")
        except Exception:
            status["gv_key_set"] = False
        try:
            from app.anki.tts import get_provider_info
            from app.ui.tts_install_worker import brew_available, kokoro_model_cache_size

            status["kokoro_available"] = bool(get_provider_info("kokoro").available)
            status["edge_available"] = bool(get_provider_info("edge").available)
            status["brew_available"] = bool(brew_available())
            status["kokoro_cache_mb"] = kokoro_model_cache_size() / 1024 / 1024
        except Exception:
            pass
        self.finished.emit(status)


class _SampleSynthWorker(QtCore.QObject):
    """Submit an interactive sample to the shared managed TTS broker."""

    finished = QtCore.Signal(bool, str, object)  # ok, error_msg, Path|None

    def __init__(self, settings, language, text) -> None:
        super().__init__()
        self._settings = settings
        self._language = language
        self._text = text

    @QtCore.Slot()
    def run(self) -> None:
        try:
            from app.tts.process_service import synthesize_text_audio_in_process

            path = synthesize_text_audio_in_process(
                self._text,
                self._language,
                self._settings,
            )
        except Exception as exc:
            self.finished.emit(False, f"{type(exc).__name__}: {exc}", None)
            return
        self.finished.emit(path is not None, "" if path else "TTS 생성 실패", path)


class _AnkiConnectTestWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    @QtCore.Slot()
    def run(self) -> None:
        try:
            from app.anki.ankiconnect_client import AnkiConnectClient

            ok = AnkiConnectClient(self._url).is_available()
        except Exception as exc:
            self.finished.emit(False, f"연결 실패: {exc}")
            return
        self.finished.emit(ok, "" if ok else "응답 없음")


class _GoogleVisionKeyTestWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)

    def __init__(self, api_key: str, endpoint: str) -> None:
        super().__init__()
        self._api_key = api_key
        self._endpoint = endpoint

    @QtCore.Slot()
    def run(self) -> None:
        try:
            from app.ocr.google_vision import test_api_key

            test_api_key(self._api_key, self._endpoint)
        except Exception as exc:
            self.finished.emit(False, str(exc) or type(exc).__name__)
            return
        self.finished.emit(True, "")
