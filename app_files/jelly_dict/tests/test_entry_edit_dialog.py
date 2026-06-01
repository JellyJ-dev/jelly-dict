from __future__ import annotations

from app.core.models import Example, VocabularyEntry
from app.ui.entry_edit_dialog import EntryEditDialog


def test_entry_edit_dialog_round_trips_user_editable_fields(qtbot):
    entry = VocabularyEntry(
        language="en",
        word="steer",
        reading="stir",
        part_of_speech=["Verb"],
        meanings_summary="조종하다",
        examples_flat=[
            Example(
                source_text_plain="He steered the boat.",
                translation_ko="그는 보트를 몰았다.",
            )
        ],
        tags=["drive"],
        memo="manual note",
        source_url="https://en.dict.naver.com",
    )
    dialog = EntryEditDialog(entry)
    qtbot.addWidget(dialog)

    dialog.word_edit.setText("steering")
    dialog.tags_edit.setText("exam, vehicle")
    dialog.memo_edit.setPlainText("edited memo")
    dialog.examples_edit.setPlainText("Example one\nExample two")
    dialog.translations_edit.setPlainText("예문 하나\n예문 둘")

    edited = dialog.current_entry()

    assert edited.word == "steering"
    assert edited.tags == ["exam", "vehicle"]
    assert edited.memo == "edited memo"
    assert [ex.source_text_plain for ex in edited.examples_flat] == [
        "Example one",
        "Example two",
    ]
    assert [ex.translation_ko for ex in edited.examples_flat] == ["예문 하나", "예문 둘"]


def test_entry_edit_dialog_requery_button_emits_signal(qtbot):
    dialog = EntryEditDialog(VocabularyEntry(language="en", word="steer"))
    qtbot.addWidget(dialog)
    seen = []
    dialog.requeryRequested.connect(lambda: seen.append(True))

    dialog.requery_button.click()

    assert seen == [True]
