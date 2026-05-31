from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from app.core.models import VocabularyEntry, normalize_word_key
from app.services.anki_sync_service import AnkiSyncService
from app.storage import excel_writer


class WordListDialog(QtWidgets.QDialog):
    """List of saved words for a given language with multi-select delete."""

    deleted = QtCore.Signal(str, int)  # language, count

    def __init__(
        self,
        excel_path_for: Callable[[str], str],
        cache_clear: Callable[[str, set[str]], None] | None = None,
        anki_sync: "AnkiSyncService | None" = None,
        language: str = "en",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._language = language if language in ("en", "ja") else "en"
        self.setWindowTitle(_wordbook_title(self._language))
        self.resize(1120, 680)
        self.setMinimumSize(980, 580)
        self._excel_path_for = excel_path_for
        self._cache_clear = cache_clear
        self._anki_sync = anki_sync

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        layout.addLayout(top)
        title = QtWidgets.QLabel(_wordbook_title(self._language))
        title.setObjectName("wordListTitle")
        top.addWidget(title)
        top.addStretch(1)

        self.sort_combo = QtWidgets.QComboBox()
        self.sort_combo.setObjectName("wordListSort")
        self.sort_combo.addItems(["최신순", "오래된순", "가나다순"])
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)
        top.addWidget(self.sort_combo)

        self.count_label = QtWidgets.QLabel("0개")
        self.count_label.setObjectName("wordListCount")
        top.addWidget(self.count_label)

        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setObjectName("wordListSearch")
        self.filter_edit.setPlaceholderText("단어 / 뜻 검색...")
        layout.addWidget(self.filter_edit)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setObjectName("wordListTable")
        self.table.setHorizontalHeaderLabels(["단어", "읽기/발음", "뜻 요약"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Fixed
        )
        self.table.setColumnWidth(0, 190)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Fixed
        )
        self.table.setColumnWidth(1, 210)
        self.table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.table.setSelectionMode(QtWidgets.QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().setDefaultSectionSize(42)
        layout.addWidget(self.table, 1)

        button_row = QtWidgets.QHBoxLayout()
        layout.addLayout(button_row)
        self.delete_btn = QtWidgets.QPushButton("선택 삭제")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
        self.delete_btn.setEnabled(False)
        button_row.addWidget(self.delete_btn)
        button_row.addStretch(1)
        close_btn = QtWidgets.QPushButton("닫기")
        close_btn.setObjectName("wordListClose")
        button_row.addWidget(close_btn)

        self.filter_edit.textChanged.connect(self._apply_filter)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.delete_btn.clicked.connect(self._delete_selected)
        close_btn.clicked.connect(self.accept)

        self._all_entries: list[VocabularyEntry] = []
        self._apply_theme()
        self._reload()

    # ---------- data ---------------------------------------------------

    def _current_language(self) -> str:
        return self._language

    def _reload(self) -> None:
        path = Path(self._excel_path_for(self._current_language()))
        language = self._current_language()
        try:
            raw_entries = excel_writer.list_entries(path)
        except Exception:
            raw_entries = []

        filtered = [
            entry
            for entry in raw_entries
            if _is_visible_entry(entry, language)
        ]

        sort_option = self.sort_combo.currentText()
        if sort_option == "오래된순":
            self._all_entries = filtered
        elif sort_option == "가나다순":
            self._all_entries = sorted(filtered, key=lambda x: (x.word or "").lower())
        else:  # "최신순"
            self._all_entries = list(reversed(filtered))

        self._apply_filter()

    def _on_sort_changed(self, text: str) -> None:
        self._reload()

    def _apply_filter(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        if needle:
            entries = [
                e
                for e in self._all_entries
                if needle in e.word.lower()
                or needle in (e.meanings_summary or "").lower()
                or needle in (e.reading or "").lower()
            ]
        else:
            entries = list(self._all_entries)

        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(entries))
        self.table.clearSelection()
        for row, entry in enumerate(entries):
            word_item = QtWidgets.QTableWidgetItem(entry.word)
            word_item.setData(QtCore.Qt.UserRole, entry)
            reading_item = QtWidgets.QTableWidgetItem(entry.reading or "")
            summary_item = QtWidgets.QTableWidgetItem(entry.meanings_summary or "")
            summary_item.setToolTip(entry.meanings_summary or "")
            for item in (word_item, reading_item, summary_item):
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(row, 0, word_item)
            self.table.setItem(row, 1, reading_item)
            self.table.setItem(row, 2, summary_item)
        self.count_label.setText(f"{len(entries)}개 / 전체 {len(self._all_entries)}")
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        self.delete_btn.setEnabled(bool(rows))
        if rows:
            self.delete_btn.setText(f"선택 삭제 ({len(rows)}개)")
        else:
            self.delete_btn.setText("선택 삭제")

    # ---------- delete -------------------------------------------------

    def _delete_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        entries = [self.table.item(r.row(), 0).data(QtCore.Qt.UserRole) for r in rows]
        words = [f"• {e.word}" for e in entries[:10]]
        more = ""
        if len(entries) > 10:
            more = f"\n... 외 {len(entries) - 10}개"
        sync_note = ""
        if self._anki_sync and self._anki_sync.enabled:
            sync_note = (
                "\n\nAnkiConnect 동기화 ON — Anki 카드도 함께 삭제 시도합니다.\n"
                "(Anki 데스크톱이 켜져 있어야 합니다)"
            )
        else:
            sync_note = (
                "\n\nAnki 덱 카드는 자동 삭제되지 않습니다.\n"
                "설정에서 AnkiConnect를 활성화하면 자동 삭제 가능합니다."
            )
        ok = QtWidgets.QMessageBox.warning(
            self,
            "삭제 확인",
            "다음 단어들을 Excel에서 삭제할까요?\n\n"
            + "\n".join(words)
            + more
            + sync_note,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return

        language = self._current_language()
        path = Path(self._excel_path_for(language))
        keys = {normalize_word_key(e.word, language) for e in entries}  # type: ignore[arg-type]
        try:
            delete_outcome = excel_writer.delete_entries_with_backup(path, language, keys)
            removed = delete_outcome.removed
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "삭제 실패", str(exc))
            return

        if self._cache_clear is not None:
            try:
                self._cache_clear(language, keys)
            except Exception:
                pass

        anki_count = 0
        anki_errors: list[str] = []
        if self._anki_sync and self._anki_sync.enabled:
            anki_count, anki_errors = self._anki_sync.delete_words(
                [e.word for e in entries],
                language,
            )

        self.deleted.emit(language, removed)
        self._show_completion_notice(
            removed,
            anki_count,
            anki_errors,
            delete_outcome.backup_path,
        )
        self._reload()

    def _show_completion_notice(
        self,
        excel_removed: int,
        anki_removed: int,
        errors: list[str],
        backup_path: Path | None,
    ) -> None:
        msg = f"Excel에서 {excel_removed}개 행을 삭제했습니다."
        if backup_path is not None:
            msg += f"\n삭제 전 백업을 만들었습니다:\n{backup_path}"
        if self._anki_sync and self._anki_sync.enabled:
            if anki_removed:
                msg += f"\nAnki에서 {anki_removed}개 카드도 삭제했습니다."
            else:
                msg += "\nAnki에 해당 카드가 없거나 동기화가 안 됐습니다."
            if errors:
                msg += "\n\n오류:\n" + "\n".join(errors[:5])
        else:
            msg += (
                "\n\nAnki에서도 같은 카드를 지우려면 직접 삭제하거나\n"
                "설정 → AnkiConnect를 활성화하세요."
            )
        QtWidgets.QMessageBox.information(self, "삭제 완료", msg)

    def _apply_theme(self) -> None:
        resource_root = (Path(__file__).resolve().parents[2] / "resources").as_posix()
        qss = """
            QDialog {
                background: #1b1b1a;
                color: #e7e1d6;
                font-family: "Apple SD Gothic Neo", "Helvetica Neue";
            }
            QLabel#wordListTitle {
                color: #f1ece2;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#wordListCount {
                color: #aaa59c;
                font-size: 13px;
                font-weight: 600;
            }
            QLineEdit#wordListSearch {
                background: #242422;
                color: #e7e1d6;
                border: 1px solid #3f3f3c;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: 600;
            }
            QComboBox#wordListSort {
                background: #242422;
                color: #e7e1d6;
                border: 1px solid #3f3f3c;
                border-radius: 10px;
                padding: 7px 28px 7px 12px;
                min-height: 24px;
                font-size: 13px;
                font-weight: 700;
            }
            QComboBox#wordListSort::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left: 1px solid #343431;
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
                background: #242422;
            }
            QComboBox#wordListSort::down-arrow {
                image: url(resources/icons/chevron_down.svg);
                width: 12px;
                height: 12px;
            }
            QLineEdit#wordListSearch::placeholder {
                color: #77746d;
            }
            QTableWidget#wordListTable {
                background: #20201f;
                color: #d4cec4;
                border: 1px solid #3f3f3c;
                border-radius: 14px;
                outline: 0;
                font-size: 13px;
                font-weight: 600;
                gridline-color: transparent;
            }
            QTableWidget#wordListTable::item {
                border-bottom: 1px solid #2b2b29;
                padding: 8px 10px;
            }
            QTableWidget#wordListTable::item:selected {
                background: #3a322d;
                color: #f1ece2;
            }
            QHeaderView::section {
                background: #2a2a28;
                color: #aaa59c;
                border: none;
                border-bottom: 1px solid #3f3f3c;
                padding: 9px 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton {
                background: #30302e;
                color: #e7e1d6;
                border: 1px solid #454542;
                border-radius: 10px;
                padding: 8px 16px;
                min-height: 28px;
                font-size: 13px;
                font-weight: 700;
                text-align: center;
            }
            QPushButton:hover {
                background: #353532;
                border-color: #6a6963;
            }
            QPushButton#dangerButton {
                color: #ff8b6b;
            }
            QPushButton#dangerButton:disabled {
                color: #6e6c66;
                border-color: #333331;
            }
            """
        self.setStyleSheet(qss.replace("url(resources/", f"url({resource_root}/"))


def _is_visible_entry(entry: VocabularyEntry, language: str) -> bool:
    if entry.language != language:
        return False
    word = (entry.word or "").strip()
    summary = (entry.meanings_summary or "").strip()
    reading = (entry.reading or "").strip()
    if not word and not summary and not reading:
        return False
    # Excel rows with only language/date metadata are artifacts, not real words.
    return bool(word)


def _wordbook_title(language: str) -> str:
    return "일본어 단어장" if language == "ja" else "영어 단어장"
