from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.word_input_components import QueueJobChip, _elide


class WordInputQueueMixin:
    def set_lookup_queue(self, jobs: list[tuple[str, str, str]]) -> None:
        # Clear existing chips
        while self.queue_chips_layout.count() > 0:
            item = self.queue_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not jobs:
            self.queue_panel.setVisible(False)
            return

        self.queue_panel.setVisible(True)
        running_count = sum(1 for _, status, _ in jobs if status == "running")
        pending_count = sum(1 for _, status, _ in jobs if status == "pending")
        failed_count = sum(1 for _, status, _ in jobs if status == "failed")

        status_text = ""
        if running_count > 0:
            status_text += f"조회 중 {running_count}개"
        if pending_count > 0:
            if status_text:
                status_text += ", "
            status_text += f"대기 {pending_count}개"
        if failed_count > 0:
            if status_text:
                status_text += ", "
            status_text += f"실패 {failed_count}개"
        self.queue_count_label.setText(status_text)

        self.queue_retry_failed_btn.setVisible(failed_count > 0)
        self.queue_clear_failed_btn.setVisible(failed_count > 0)

        MAX_VISIBLE_CHIPS = 10
        has_more = len(jobs) > MAX_VISIBLE_CHIPS
        display_jobs = jobs[:MAX_VISIBLE_CHIPS - 1] if has_more else jobs

        for word, status, job_id in display_jobs:
            if status == "running":
                chip = QtWidgets.QPushButton()
                chip.setObjectName("queueChipRunning")
                chip.setText(f"진행 · {_elide(word, 22)}")
                chip.setCursor(QtCore.Qt.ArrowCursor)
                chip.setToolTip(f"'{word}' (조회 중...)")
            elif status == "failed":
                chip = QueueJobChip()
                chip.setObjectName("queueChipFailed")
                chip.setText(f"실패 · {_elide(word, 22)}")
                chip.setCursor(QtCore.Qt.PointingHandCursor)
                chip.setToolTip(f"'{word}' (조회 실패. 클릭: 재시도, 우클릭: 삭제)")
                chip.clicked.connect(lambda checked=False, jid=job_id: self.jobRetryRequested.emit(jid))
                chip.rightClicked.connect(lambda jid=job_id: self.jobCancelRequested.emit(jid))
            else:
                chip = QtWidgets.QPushButton()
                chip.setObjectName("queueChipPending")
                chip.setText(_elide(word, 24))
                chip.setCursor(QtCore.Qt.PointingHandCursor)
                chip.setToolTip(f"'{word}' (대기열에서 취소하려면 클릭)")
                chip.clicked.connect(lambda checked=False, jid=job_id: self.jobCancelRequested.emit(jid))

            self.queue_chips_layout.addWidget(chip)

        if has_more:
            more_count = len(jobs) - len(display_jobs)
            more_chip = QtWidgets.QPushButton()
            more_chip.setObjectName("queueChipMore")
            more_chip.setText(f"+ 외 {more_count}개")
            more_chip.setCursor(QtCore.Qt.PointingHandCursor)

            hidden_jobs = jobs[len(display_jobs):]
            remaining_words = [w for w, _, _ in hidden_jobs]
            if len(remaining_words) > 30:
                tooltip_text = "대기 단어 (클릭하면 상세 조작 가능):\n" + ", ".join(remaining_words[:30]) + f"\n... 외 {len(remaining_words) - 30}개"
            else:
                tooltip_text = "대기 단어 (클릭하면 상세 조작 가능):\n" + ", ".join(remaining_words)
            more_chip.setToolTip(tooltip_text)

            def show_more_menu() -> None:
                menu = QtWidgets.QMenu(more_chip)
                menu.setObjectName("languageMenu")
                for word, status, job_id in hidden_jobs:
                    if status == "failed":
                        retry_act = menu.addAction(f"실패 · {word} (조회 재시도)")
                        retry_act.triggered.connect(lambda checked=False, jid=job_id: self.jobRetryRequested.emit(jid))
                        delete_act = menu.addAction(f"{word} (대기 삭제)")
                        delete_act.triggered.connect(lambda checked=False, jid=job_id: self.jobCancelRequested.emit(jid))
                    else:
                        cancel_act = menu.addAction(f"{word} (대기 취소)")
                        cancel_act.triggered.connect(lambda checked=False, jid=job_id: self.jobCancelRequested.emit(jid))

                pos = more_chip.mapToGlobal(QtCore.QPoint(0, more_chip.height()))
                menu.exec(pos)

            more_chip.clicked.connect(show_more_menu)
            self.queue_chips_layout.addWidget(more_chip)
