from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.export_plan import ExportPlan
from app.core.settings import Settings
from app.services.ports import ExportCapabilitiesPort

Severity = Literal["block", "warn", "info"]


@dataclass(frozen=True)
class PreflightIssue:
    severity: Severity
    message: str


@dataclass(frozen=True)
class PreflightResult:
    issues: tuple[PreflightIssue, ...]

    @property
    def blockers(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "block")

    @property
    def warnings(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warn")

    @property
    def infos(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "info")


def run_export_preflight(
    settings: Settings,
    plan: ExportPlan,
    *,
    output_path: Path,
    capabilities: ExportCapabilitiesPort,
) -> PreflightResult:
    issues: list[PreflightIssue] = []
    excel_path = Path(settings.excel_path_for(plan.language)).expanduser()
    if not excel_path.exists():
        issues.append(PreflightIssue("block", "Excel 단어장 파일을 찾을 수 없습니다."))
    if plan.card_count == 0:
        issues.append(PreflightIssue("block", "내보낼 카드가 없습니다."))
    if output_path.exists():
        issues.append(PreflightIssue("warn", "같은 이름의 APKG 파일을 덮어씁니다."))

    if not capabilities.genanki_available():
        issues.append(PreflightIssue("block", "genanki가 설치되어 있지 않습니다."))

    if plan.audio_policy == "remove_audio":
        issues.append(
            PreflightIssue(
                "warn",
                "기존 Anki 카드에서 음성을 제거하려면 가져오기 시 기존 노트 업데이트가 필요합니다.",
            )
        )

    if plan.effective_tts_enabled:
        _check_tts(settings, plan, issues, capabilities)
    return PreflightResult(tuple(issues))


def _check_tts(
    settings: Settings,
    plan: ExportPlan,
    issues: list[PreflightIssue],
    capabilities: ExportCapabilitiesPort,
) -> None:
    engine = plan.tts_engine
    if not engine or engine == "none":
        issues.append(PreflightIssue("block", "TTS가 켜져 있지만 선택된 엔진이 없습니다."))
        return

    try:
        capability_getter = getattr(
            capabilities,
            "tts_provider_capabilities",
            None,
        )
        capability = capability_getter(engine) if callable(capability_getter) else None
        info = capabilities.tts_provider_info(engine) if capability is None else None
    except Exception as exc:
        issues.append(PreflightIssue("block", f"TTS 엔진 상태 확인 실패: {exc}"))
        return

    if capability is not None:
        if capability.availability_for(plan.language) == "missing":
            issues.append(
                PreflightIssue(
                    "block",
                    f"{capability.display_name} 엔진이 설치되어 있지 않습니다.",
                )
            )
            return
        voices = capability.voices_for(plan.language)
        if (
            plan.tts_voice
            and capability.availability_for_voice(
                plan.language,
                plan.tts_voice,
            )
            == "missing"
        ):
            issues.append(
                PreflightIssue(
                    "block",
                    "선택한 TTS 음성의 로컬 파일 또는 의존성이 없습니다.",
                )
            )
            return
    else:
        if not info.available:
            issues.append(
                PreflightIssue("block", f"{info.display_name} 엔진이 설치되어 있지 않습니다.")
            )
            return
        voices = info.voices_ja if plan.language == "ja" else info.voices_en
    if engine == "voicevox" and plan.language == "ja":
        voices = tuple(getattr(settings, "tts_voicevox_voices", ()) or voices)
        try:
            if not capabilities.voicevox_running(settings.voicevox_url, timeout=0.3):
                issues.append(PreflightIssue("block", "VOICEVOX 엔진이 실행 중이 아닙니다."))
        except Exception as exc:
            issues.append(PreflightIssue("block", f"VOICEVOX 상태 확인 실패: {exc}"))

    if not plan.tts_voice:
        issues.append(PreflightIssue("block", "선택된 TTS 음성이 없습니다."))
    elif voices and plan.tts_voice not in voices:
        issues.append(PreflightIssue("warn", "선택한 TTS 음성이 현재 음성 목록에 없습니다."))

    if plan.tts_play_examples and plan.card_count >= 50:
        issues.append(
            PreflightIssue(
                "warn",
                "예문 음성이 켜져 있어 카드 수가 많으면 생성 시간이 길어질 수 있습니다.",
            )
        )
