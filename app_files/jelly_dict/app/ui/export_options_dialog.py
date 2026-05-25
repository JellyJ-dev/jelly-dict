from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from app.services.export_preflight import PreflightResult
from app.ui.export_options import ExportOptions, ExportPlan, language_label


class _ElideLabel(QtWidgets.QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._full_text = text
        self.setObjectName("settingsStatus")
        self.setToolTip(text)
        self.setMinimumWidth(180)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text
        self.setToolTip(text)
        super().setText(self._elided())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        super().setText(self._elided())

    def _elided(self) -> str:
        metrics = self.fontMetrics()
        return metrics.elidedText(self._full_text, QtCore.Qt.ElideMiddle, max(80, self.width()))


class ExportOptionsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        plan: ExportPlan,
        output_path: Path,
        preflight: PreflightResult,
        force_options: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._output_path = output_path
        self._preflight = preflight
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Anki 내보내기 확인")
        self.setMinimumWidth(560)
        self.resize(620, 420)
        self._build_ui(force_options)

    def selected_options(self) -> ExportOptions:
        policy = self.policy_combo.currentData() or "settings"
        return ExportOptions(
            audio_policy=policy,
            save_as_default=self.save_default_check.isChecked(),
            suppress_future_confirm=self.skip_check.isChecked(),
        )

    def _build_ui(self, force_options: bool) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QtWidgets.QLabel("내보내기 전 확인")
        title.setObjectName("exportDialogTitle")
        root.addWidget(title)
        subtitle = QtWidgets.QLabel(
            f"{language_label(self._plan.language)} · {self._plan.audio_summary}"
        )
        subtitle.setObjectName("exportDialogSubtitle")
        root.addWidget(subtitle)

        summary = QtWidgets.QFrame()
        summary.setObjectName("settingsPanel")
        form = QtWidgets.QFormLayout(summary)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(7)
        self._add_row(form, "언어", self._value_label(language_label(self._plan.language)))
        self._add_row(form, "카드 수", self._value_label(f"{self._plan.card_count}개"))
        self._add_row(form, "덱", self._value_label(self._plan.deck_name))
        self._add_row(form, "저장 위치", _ElideLabel(str(self._output_path)))
        root.addWidget(summary)

        self.policy_combo = QtWidgets.QComboBox()
        self.policy_combo.setObjectName("settingsCombo")
        for label, value in [
            ("현재 설정 사용", "settings"),
            ("이번만 TTS 포함", "force_tts"),
            ("이번만 TTS 제외", "no_tts"),
            ("기존 Anki 음성 제거용", "remove_audio"),
        ]:
            self.policy_combo.addItem(label, value)
        idx = self.policy_combo.findData(self._plan.audio_policy)
        if idx >= 0:
            self.policy_combo.setCurrentIndex(idx)
        self._add_row(root, "TTS 모드", self.policy_combo)

        status = QtWidgets.QLabel(self._status_text())
        status.setObjectName("exportStatusBlock")
        status.setWordWrap(True)
        root.addWidget(status)

        issue_text = self._issue_text()
        if issue_text:
            issues = QtWidgets.QLabel(issue_text)
            issues.setObjectName("exportWarningBlock")
            issues.setWordWrap(True)
            root.addWidget(issues)

        self.save_default_check = QtWidgets.QCheckBox("이번 설정을 기본값으로 저장")
        self.skip_check = QtWidgets.QCheckBox("이 확인창 다시 보지 않기")
        if force_options:
            self.skip_check.setVisible(True)
        root.addWidget(self.save_default_check)
        root.addWidget(self.skip_check)
        root.addStretch(1)

        buttons = QtWidgets.QDialogButtonBox()
        export_btn = buttons.addButton("내보내기", QtWidgets.QDialogButtonBox.AcceptRole)
        export_btn.setObjectName("settingsPrimaryButton")
        cancel_btn = buttons.addButton("취소", QtWidgets.QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("settingsSecondaryButton")
        detail_btn = buttons.addButton("상세 설정", QtWidgets.QDialogButtonBox.ActionRole)
        detail_btn.setObjectName("settingsSecondaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        detail_btn.clicked.connect(self._open_settings)
        root.addWidget(buttons, 0, QtCore.Qt.AlignRight)

    def _value_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("exportMetaValue")
        return label

    def _add_row(self, layout, label_text: str, widget: QtWidgets.QWidget) -> None:
        label = QtWidgets.QLabel(label_text)
        label.setObjectName("exportFormLabel")
        if isinstance(layout, QtWidgets.QFormLayout):
            layout.addRow(label, widget)
        else:
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(label)
            row_layout.addWidget(widget, 1)
            layout.addWidget(row)

    def _status_text(self) -> str:
        voice = self._plan.tts_voice or "음성 없음"
        examples = "켜짐" if self._plan.tts_play_examples else "꺼짐"
        front = "켜짐" if self._plan.tts_play_front else "꺼짐"
        back = "켜짐" if self._plan.tts_play_back else "꺼짐"
        return (
            f"{self._plan.audio_summary}\n"
            f"엔진/음성: {self._plan.tts_engine} / {voice}\n"
            f"예문 음성: {examples} · 앞면 자동 재생: {front} · 뒷면 자동 재생: {back}"
        )

    def _issue_text(self) -> str:
        lines: list[str] = []
        for issue in self._preflight.blockers:
            lines.append(f"진행 불가: {issue.message}")
        for issue in self._preflight.warnings:
            lines.append(f"확인 필요: {issue.message}")
        return "\n".join(lines)

    def _open_settings(self) -> None:
        self.done(2)
