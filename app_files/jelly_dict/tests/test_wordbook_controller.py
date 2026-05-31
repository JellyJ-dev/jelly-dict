from __future__ import annotations

from pathlib import Path

from app.core.models import Example, VocabularyEntry
from app.storage import excel_writer
from app.storage.settings_store import Settings
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.widgets.wordbook_items import WordbookDisplayItem


class _InputView:
    def __init__(self) -> None:
        self.language = ""
        self.items = []

    def set_wordbook(self, language: str, items: list[WordbookDisplayItem]) -> None:
        self.language = language
        self.items = items


class _StatusBar:
    def __init__(self) -> None:
        self.message = ""

    def showMessage(self, message: str) -> None:  # noqa: N802 - Qt API shape
        self.message = message


def test_wordbook_controller_preserves_metadata_for_inline_display(tmp_path):
    path = tmp_path / "vocab_en.xlsx"
    settings = Settings(excel_path_en=str(path))
    entry = VocabularyEntry(
        language="en",
        word="apple",
        tags=["exam", "fruit"],
        memo="중요 단어",
        examples_flat=[
            Example(
                source_text_plain="An apple a day",
                translation_ko="하루 사과 하나",
            )
        ],
        updated_at="2026-05-31T12:00:00+00:00",
    )
    excel_writer.append_entry(Path(settings.excel_path_for("en")), entry, settings.excel_columns)
    input_view = _InputView()
    status = _StatusBar()
    controller = WordbookController(
        parent=None,  # type: ignore[arg-type]
        input_view=input_view,  # type: ignore[arg-type]
        cache=None,  # type: ignore[arg-type]
        anki_sync=None,  # type: ignore[arg-type]
        settings=settings,
        status_bar=status,  # type: ignore[arg-type]
    )

    controller.show_inline("en")

    assert input_view.language == "en"
    assert len(input_view.items) == 1
    item = input_view.items[0]
    assert isinstance(item, WordbookDisplayItem)
    assert item.tags == ("exam", "fruit")
    assert item.memo == "중요 단어"
    assert item.examples == ("An apple a day 하루 사과 하나",)
    assert item.updated_at.startswith("2026-05-31")
    assert "영어 단어장 1개" in status.message
