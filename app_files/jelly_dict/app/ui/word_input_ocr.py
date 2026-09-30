from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.word_input_parts.chips import OcrCandidateChip
from app.ui.word_input_parts.text_parsing import _elide
from app.ui.word_input_ui_refs import WordInputUiRefs


class OcrPresenter:
    def __init__(self, ui: WordInputUiRefs, facade: object) -> None:
        self.ui = ui
        self._state = facade
        self._signals = facade

    def show_ocr_image(self, image_path: str) -> None:
        pixmap = QtGui.QPixmap(image_path)
        if not pixmap.isNull():
            self.ui.ocr_thumbnail.setPixmap(
                pixmap.scaled(
                    self.ui.ocr_thumbnail.size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            )
        else:
            self.ui.ocr_thumbnail.clear()
        self._state._ocr_tokens = []
        self._state._ocr_selected_tokens = []
        self._state._ocr_chip_buttons = {}
        self._set_ocr_status("사진 텍스트 인식 중...")
        self._render_ocr_chips()
        self._set_ocr_area_visible(True)

    def set_ocr_tokens(self, tokens: list[str]) -> None:
        self._state._ocr_tokens = list(tokens)
        if tokens:
            self._set_ocr_status(f"후보 {len(tokens)}개")
            self._render_ocr_chips()
        else:
            self._set_ocr_status("인식된 단어 후보 없음")
            self._render_ocr_chips()
        self._set_ocr_area_visible(True)

    def set_ocr_error(self, message: str) -> None:
        self._state._ocr_tokens = []
        self._set_ocr_status(message)
        self._render_ocr_chips()
        self._set_ocr_area_visible(True)

    def clear_ocr_image(self) -> None:
        self.ui.ocr_thumbnail.clear()
        self._state._ocr_tokens = []
        self._state._ocr_selected_tokens = []
        self._state._ocr_chip_buttons = {}
        self._set_ocr_status("")
        self._render_ocr_chips()
        self._set_ocr_area_visible(False)
        self._signals.ocrCleared.emit()

    def _set_ocr_area_visible(self, visible: bool) -> None:
        if self._state._ocr_height_animation is not None:
            self._state._ocr_height_animation.stop()

        if visible:
            self.ui.ocr_area.setVisible(True)
            self.ui.ocr_area.adjustSize()
        target_height = self.ui.ocr_area.sizeHint().height() if visible else 0
        start_height = self.ui.ocr_area.height() if self.ui.ocr_area.isVisible() else 0

        self._state._ocr_height_animation = QtCore.QVariantAnimation(self._state)
        self._state._ocr_height_animation.setStartValue(start_height)
        self._state._ocr_height_animation.setEndValue(target_height)
        self._state._ocr_height_animation.setDuration(180)
        self._state._ocr_height_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._state._ocr_height_animation.valueChanged.connect(
            lambda value: self.ui.ocr_area.setMaximumHeight(int(value))
        )
        self._state._ocr_height_animation.finished.connect(
            lambda: self._finish_ocr_area_animation(visible)
        )
        self._state._ocr_height_animation.start()

    def _finish_ocr_area_animation(self, visible: bool) -> None:
        if visible:
            self.ui.ocr_area.setMaximumHeight(16777215)
            return
        self.ui.ocr_area.setVisible(False)
        self.ui.ocr_area.setMaximumHeight(0)

    def _set_ocr_status(self, text: str) -> None:
        self.ui.ocr_status.setText(text)

    def _render_ocr_chips(self, selectable: bool = True) -> None:
        layout = self.ui.ocr_candidates_layout
        while layout.count() > 0:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._state._ocr_chip_buttons = {}
        for token in self._state._ocr_tokens:
            button = OcrCandidateChip(_elide(token, 28))
            button.setObjectName("ocrChipButton")
            button.setToolTip(f"'{token}' (클릭: 선택, 더블클릭: 편집, 우클릭: 삭제)")
            if selectable:
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, t=token: self._choose_ocr_token(t, checked)
                )
                button.setChecked(token in self._state._ocr_selected_tokens)
            else:
                button.clicked.connect(lambda _=False, t=token: self._fill_from_ocr_token(t))

            button.doubleClicked.connect(lambda t=token: self._edit_ocr_token(t))
            button.rightClicked.connect(lambda t=token: self._delete_ocr_token(t))

            self._state._ocr_chip_buttons[token] = button
            layout.addWidget(button)

        self.ui.ocr_bulk_lookup_btn.setEnabled(bool(self._state._ocr_tokens))

        self.ui.ocr_candidates.updateGeometry()
        self.ui.ocr_area.updateGeometry()

    def _edit_ocr_token(self, token: str) -> None:
        new_text, ok = QtWidgets.QInputDialog.getText(
            self._state, "후보 수정", "후보 단어 수정:", text=token
        )
        if not ok:
            return
        new_text = new_text.strip()
        if not new_text or new_text == token:
            return

        if token in self._state._ocr_tokens:
            idx = self._state._ocr_tokens.index(token)
            self._state._ocr_tokens[idx] = new_text

        if token in self._state._ocr_selected_tokens:
            s_idx = self._state._ocr_selected_tokens.index(token)
            self._state._ocr_selected_tokens[s_idx] = new_text

        self._render_ocr_chips()

    def _delete_ocr_token(self, token: str) -> None:
        self._state._ocr_tokens = [t for t in self._state._ocr_tokens if t != token]
        self._state._ocr_selected_tokens = [
            t for t in self._state._ocr_selected_tokens if t != token
        ]
        self._set_ocr_status(f"후보 {len(self._state._ocr_tokens)}개")
        self._render_ocr_chips()

    def _on_ocr_bulk_lookup_clicked(self) -> None:
        targets = (
            self._state._ocr_selected_tokens
            if self._state._ocr_selected_tokens
            else self._state._ocr_tokens
        )
        if targets:
            self._signals.ocrBulkLookupRequested.emit(targets, self._state._forced_language)

    def _choose_ocr_token(self, token: str, selected: bool) -> None:
        if selected:
            if token not in self._state._ocr_selected_tokens:
                self._state._ocr_selected_tokens.append(token)
            self._fill_from_ocr_token(token)
            self._signals.ocrTokenSelected.emit(token)
            return
        self._state._ocr_selected_tokens = [
            selected_token
            for selected_token in self._state._ocr_selected_tokens
            if selected_token != token
        ]
        if self._state._ocr_selected_tokens:
            self._fill_from_ocr_token(self._state._ocr_selected_tokens[-1])
        else:
            self.ui.input.clear()
            self.ui.input.setFocus()

    def _fill_from_ocr_token(self, token: str) -> None:
        self.ui.input.setText(token)
        self.ui.input.setFocus()
        self.ui.input.selectAll()

    def selected_ocr_tokens(self) -> list[str]:
        return list(self._state._ocr_selected_tokens)


__all__ = ["OcrPresenter"]
