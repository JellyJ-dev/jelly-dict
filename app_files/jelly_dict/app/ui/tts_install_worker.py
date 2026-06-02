"""Background workers that install TTS-related deps.

Routing policy: prefer Homebrew when a brew package is available, fall
back to pip / pipx, fall back to "open the download page" if neither
helper is on PATH. This keeps installs uniform across engines while
preserving the GPL isolation of edge-tts (which is installed only via
pipx into its own venv, never imported by jelly_dict).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6 import QtCore

log = logging.getLogger(__name__)


def brew_available() -> bool:
    return shutil.which("brew") is not None


def pipx_available() -> bool:
    return shutil.which("pipx") is not None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def kokoro_model_cache_path() -> Path:
    """Path of the cached Kokoro model in the HF hub cache."""
    return (
        Path.home() / ".cache" / "huggingface" / "hub" / "models--hexgrad--Kokoro-82M"
    )


def kokoro_model_cache_size() -> int:
    """Total bytes used by the cached Kokoro model, or 0 if not present."""
    base = kokoro_model_cache_path()
    if not base.exists():
        return 0
    total = 0
    for f in base.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            continue
    return total


class _BaseInstallWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)
    progress = QtCore.Signal(str)
    open_url = QtCore.Signal(str)  # ask the UI to open a fallback URL

    def _run(self, cmd: list[str], label: str, timeout: int = 900) -> tuple[bool, str]:
        """Run ``cmd`` and stream its combined stdout/stderr line by line.

        Each line is logged and emitted via ``progress`` so the UI shows
        live activity (otherwise pip on a heavy dep like torch would look
        frozen for minutes while output stays buffered).
        """
        self.progress.emit(f"{label} 시작…")
        log.info("install: %s", " ".join(cmd))
        # Force unbuffered child output so we can read it as it appears.
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PIP_PROGRESS_BAR"] = "off"
        # Brew can hang on background analytics / auto-update / sudo-prompt
        # if any of these are left at defaults. Cut them all off so the
        # process exits as soon as the visible work is done.
        env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
        env["HOMEBREW_NO_ANALYTICS"] = "1"
        env["HOMEBREW_NO_INSTALL_CLEANUP"] = "1"
        env["HOMEBREW_NO_ENV_HINTS"] = "1"
        env["NONINTERACTIVE"] = "1"
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,  # never wait for user input
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,    # isolate from our process group
            )
        except FileNotFoundError as exc:
            return False, f"{cmd[0]} 실행 실패: {exc}"

        import select

        deadline = time.monotonic() + timeout
        idle_timeout = 30.0  # kill if no output AND not exited for this long
        recent: list[str] = []
        try:
            assert proc.stdout is not None
            fd = proc.stdout.fileno()
            buf = ""
            last_progress = time.monotonic()
            while True:
                if time.monotonic() > deadline:
                    proc.kill()
                    return False, f"{label} 시간 초과 ({timeout}초)"
                # Wait up to 1s for data so we can also check exit status.
                ready, _, _ = select.select([fd], [], [], 1.0)
                if ready:
                    chunk = os.read(fd, 4096)
                    if not chunk:  # EOF — child closed stdout
                        break
                    last_progress = time.monotonic()
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.rstrip()
                        if not line:
                            continue
                        log.info("[%s] %s", label, line)
                        recent.append(line)
                        if len(recent) > 12:
                            recent = recent[-12:]
                        self.progress.emit(f"{label}… {line[:140]}")
                else:
                    # No new output — has the process finished?
                    if proc.poll() is not None:
                        break
                    # Or has it gone idle far too long? Probably hung.
                    if time.monotonic() - last_progress > idle_timeout:
                        proc.kill()
                        return False, (
                            f"{label} 응답 없음 ({idle_timeout:.0f}초간 출력 없음). "
                            "프로세스를 종료했습니다."
                        )
            if buf.strip():
                log.info("[%s] %s", label, buf.strip())
                recent.append(buf.strip())
        except Exception as exc:
            proc.kill()
            return False, f"{label} 출력 읽기 실패: {exc}"

        rc = proc.wait()
        if rc != 0:
            tail = "\n".join(recent[-5:]) or "(no output)"
            return False, f"{label} 실패 (code {rc}):\n{tail}"
        return True, ""


class KokoroInstallWorker(_BaseInstallWorker):
    """Kokoro = pip-only (Apache-2.0 / MIT). Also pulls in ffmpeg via brew
    when available so the WAV → MP3 normalization step works.

    Japanese support requires the ``misaki[ja]`` extra (which depends on
    ``pyopenjtalk`` for phoneme conversion). We install it as a second,
    best-effort step so English TTS still works even if pyopenjtalk fails
    to build on the user's machine.
    """

    PACKAGES_CORE = ("kokoro>=0.3", "soundfile>=0.12")
    PACKAGES_JA = ("misaki[ja]>=0.6.7",)

    @QtCore.Slot()
    def run(self) -> None:
        if not ffmpeg_available() and brew_available():
            ok, msg = self._run(
                ["brew", "install", "ffmpeg"], "ffmpeg 설치", timeout=900,
            )
            if not ok:
                self.finished.emit(False, msg)
                return

        core_cmd = [
            sys.executable, "-m", "pip", "install",
            "--upgrade", "--disable-pip-version-check",
            *self.PACKAGES_CORE,
        ]
        ok, msg = self._run(core_cmd, "Kokoro / soundfile 설치", timeout=1200)
        if not ok:
            self.finished.emit(False, msg)
            return

        from app.anki.tts.kokoro_provider import KOKORO_REPO_ID, KOKORO_REQUIRED_FILES

        snapshot_code = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download({KOKORO_REPO_ID!r}, "
            f"allow_patterns={list(KOKORO_REQUIRED_FILES)!r})"
        )
        model_ok, model_msg = self._run(
            [sys.executable, "-c", snapshot_code],
            "Kokoro 로컬 모델 캐시 설치",
            timeout=1200,
        )
        if not model_ok:
            self.finished.emit(False, model_msg)
            return

        en_ok, en_msg = self._run(
            [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
            "영어 G2P 모델 설치",
            timeout=900,
        )
        if not en_ok:
            self.finished.emit(
                False,
                "Kokoro 영어 TTS용 spaCy 모델 설치 실패:\n"
                f"{en_msg}\n"
                "설치가 끝나기 전에는 영어 TTS가 실행 중 자동 다운로드를 시도하지 않습니다.",
            )
            return

        # Japanese deps — best effort. pyopenjtalk needs a C build on
        # some platforms; if it fails we still report success for English.
        ja_cmd = [
            sys.executable, "-m", "pip", "install",
            "--upgrade", "--disable-pip-version-check",
            *self.PACKAGES_JA,
        ]
        ja_ok, ja_msg = self._run(ja_cmd, "일본어 음소 모듈 설치", timeout=900)
        if not ja_ok:
            log.warning("misaki[ja] install failed: %s", ja_msg)
            self.finished.emit(
                True,
                "Kokoro 설치 완료. 영어는 사용 가능하지만 일본어는 추가 모듈 "
                "(pyopenjtalk) 설치 실패로 동작하지 않을 수 있습니다.",
            )
            return

        # The `unidic` Python package only ships metadata; the actual
        # MeCab dictionary (~250MB) has to be fetched separately with
        # `python -m unidic download`. Without this fugashi raises
        # "no such file or directory: .../unidic/dicdir/mecabrc".
        unidic_ok, unidic_msg = self._run(
            [sys.executable, "-m", "unidic", "download"],
            "일본어 사전(unidic) 다운로드", timeout=900,
        )
        if unidic_ok:
            self.finished.emit(
                True, "Kokoro 설치 완료 (영어 + 일본어). 앱을 재시작하세요.",
            )
        else:
            log.warning("unidic download failed: %s", unidic_msg)
            self.finished.emit(
                True,
                "Kokoro 설치 완료. 영어는 즉시 사용 가능하며 일본어는 "
                "MeCab 사전 다운로드 실패로 동작하지 않을 수 있습니다. "
                "터미널에서 `python -m unidic download`를 실행해 보세요.",
            )


VOICEVOX_DOWNLOAD_URL = "https://voicevox.hiroshiba.jp/"


class VoicevoxInstallWorker(_BaseInstallWorker):
    """VOICEVOX desktop app installer.

    VOICEVOX is NOT in homebrew-cask main repo and the project doesn't
    publish an official tap, so plain ``brew install --cask voicevox``
    fails with "No Cask with this name exists". When that happens we
    auto-open the official download page as the next-best UX.
    """

    @QtCore.Slot()
    def run(self) -> None:
        # VOICEVOX is NOT in homebrew-cask main repo and the project
        # doesn't publish an official tap. Skip the brew attempt entirely
        # — brew can hang for tens of seconds doing analytics/cleanup
        # before reporting "No Cask with this name exists", which is a
        # bad UX for something we know will fail.
        self.open_url.emit(VOICEVOX_DOWNLOAD_URL)
        self.finished.emit(
            False,
            "VOICEVOX는 Homebrew에 등록돼 있지 않아 공식 다운로드 페이지를 "
            "열었습니다. 내려받은 .dmg를 실행해 설치하세요.",
        )


class EdgeTtsInstallWorker(_BaseInstallWorker):
    """edge-tts via pipx — isolated from jelly_dict's venv, GPL contained.
    pipx itself is bootstrapped via brew when needed."""

    @QtCore.Slot()
    def run(self) -> None:
        if not pipx_available():
            if not brew_available():
                self.finished.emit(
                    False,
                    "pipx 또는 Homebrew가 필요합니다. https://brew.sh 또는 "
                    "pipx 공식 문서를 참고하세요.",
                )
                return
            ok, msg = self._run(["brew", "install", "pipx"], "pipx 설치")
            if not ok:
                self.finished.emit(False, msg)
                return
            # ensurepath updates the user's shell profile so future shells
            # find the pipx-installed binaries.
            self._run(["pipx", "ensurepath"], "pipx 경로 설정", timeout=60)

        ok, msg = self._run(["pipx", "install", "edge-tts"], "edge-tts 설치", timeout=300)
        if not ok:
            self.finished.emit(False, msg)
            return
        self.finished.emit(
            True,
            "edge-tts 설치 완료. (별도 venv에 격리되어 jelly_dict 라이선스에 영향 없음)",
        )


# Kept for backwards compatibility with earlier imports.
TTSInstallWorker = KokoroInstallWorker


# ── Uninstall workers ─────────────────────────────────────────────────

class KokoroUninstallWorker(_BaseInstallWorker):
    """Remove Kokoro / soundfile pip packages and the cached HF model.

    Heavy transitive deps (torch, numpy, scipy) are intentionally left
    in place — the user may have installed them for other purposes and
    silently ripping them out could break unrelated tools.
    """

    # Direct deps only — heavy transitives (torch / numpy / scipy) stay
    # so we don't break unrelated tools the user might have installed.
    # `unidic` and `fugashi` are bundled because they're only ever pulled
    # in by misaki[ja] for Kokoro Japanese support.
    PACKAGES = ("kokoro", "soundfile", "misaki", "fugashi", "unidic")

    @QtCore.Slot()
    def run(self) -> None:
        cmd = [
            sys.executable, "-m", "pip", "uninstall", "-y",
            "--disable-pip-version-check",
            *self.PACKAGES,
        ]
        ok, msg = self._run(cmd, "Kokoro 패키지 삭제", timeout=180)
        if not ok:
            self.finished.emit(False, msg)
            return

        freed = 0
        cache = kokoro_model_cache_path()
        if cache.exists():
            freed = kokoro_model_cache_size()
            try:
                shutil.rmtree(cache, ignore_errors=True)
            except Exception as exc:
                self.finished.emit(
                    False, f"패키지는 삭제됐지만 모델 캐시 정리 실패: {exc}",
                )
                return

        msg = "Kokoro 삭제 완료"
        if freed:
            msg += f" (모델 캐시 {freed / 1024 / 1024:.0f}MB 정리)"
        msg += ". 앱을 재시작하면 적용됩니다."
        self.finished.emit(True, msg)


class VoicevoxUninstallWorker(_BaseInstallWorker):
    """Uninstall VOICEVOX via Homebrew. If brew isn't available or the
    user installed it manually we surface a friendly hint instead."""

    @QtCore.Slot()
    def run(self) -> None:
        if not brew_available():
            self.finished.emit(
                False,
                "Homebrew가 없어 자동 삭제할 수 없습니다. "
                "/Applications/VOICEVOX.app을 휴지통으로 이동해 주세요.",
            )
            return
        ok, msg = self._run(
            ["brew", "uninstall", "--cask", "voicevox"],
            "VOICEVOX 삭제", timeout=300,
        )
        if ok:
            self.finished.emit(True, "VOICEVOX 삭제 완료.")
            return
        # If brew thinks it's not installed, treat that as a nudge.
        if "not installed" in msg.lower() or "no such" in msg.lower():
            self.finished.emit(
                False,
                "Homebrew가 VOICEVOX를 설치한 기록이 없습니다. 직접 설치한 경우 "
                "/Applications/VOICEVOX.app을 휴지통으로 이동해 주세요.",
            )
            return
        self.finished.emit(False, msg)


class EdgeTtsUninstallWorker(_BaseInstallWorker):
    """Uninstall edge-tts from its pipx-managed venv."""

    @QtCore.Slot()
    def run(self) -> None:
        if not pipx_available():
            self.finished.emit(
                False,
                "pipx가 없어 자동 삭제할 수 없습니다. 직접 설치한 경우 "
                "해당 환경에서 `pip uninstall edge-tts`를 실행하세요.",
            )
            return
        ok, msg = self._run(
            ["pipx", "uninstall", "edge-tts"],
            "edge-tts 삭제", timeout=120,
        )
        if ok:
            self.finished.emit(True, "edge-tts 삭제 완료.")
            return
        if "not installed" in msg.lower() or "nothing to" in msg.lower():
            self.finished.emit(False, "pipx에 edge-tts가 설치돼 있지 않습니다.")
            return
        self.finished.emit(False, msg)
