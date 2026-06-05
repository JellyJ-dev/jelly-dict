from __future__ import annotations

from PySide6 import QtWidgets


def confirm_lookup_suggestion(
    parent: QtWidgets.QWidget,
    typed: str,
    suggestion: str,
    detected_language: str,
) -> bool:
    msg = QtWidgets.QMessageBox(parent)
    msg.setIcon(QtWidgets.QMessageBox.Question)
    msg.setWindowTitle("혹시 이걸 찾으셨나요?")
    msg.setText(
        f"입력하신 <b>{typed}</b> 와 사전이 반환한 표제어가 다릅니다.\n"
        f"혹시 <b>{suggestion}</b> 을 찾으신 건가요?"
    )
    accept = msg.addButton("네, 그걸로 저장", QtWidgets.QMessageBox.AcceptRole)
    msg.addButton("아니요, 다시 입력", QtWidgets.QMessageBox.RejectRole)
    msg.exec()
    return msg.clickedButton() is accept
