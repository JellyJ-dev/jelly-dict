"""Explicit widget references shared by word-input presenters."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class WordInputUiRefs:
    root_layout: Any
    top_area: Any
    title: Any
    command_panel: Any
    input: Any
    ocr_area: Any
    ocr_thumbnail: Any
    ocr_status: Any
    ocr_clear_btn: Any
    ocr_candidates_label: Any
    ocr_candidates: Any
    ocr_candidates_layout: Any
    ocr_bulk_lookup_btn: Any
    lookup_slot: Any
    lookup_btn: Any
    lookup_busy: Any
    lookup_busy_label: Any
    lookup_spinner: Any
    lookup_width_animation: Any
    image_btn: Any
    lang_button: Any
    ocr_model_btn: Any
    settings_btn: Any
    queue_panel: Any
    queue_count_label: Any
    queue_stop_btn: Any
    queue_retry_failed_btn: Any
    queue_clear_failed_btn: Any
    queue_chips_frame: Any
    queue_chips_layout: Any
    recent_panel: Any
    recent_title_btn: Any
    clear_recent_btn: Any
    wordbook_search: Any
    wordbook_sort_btn: Any
    wordbook_stats: Any
    wordbook_expand_btn: Any
    wordbook_export_btn: Any
    wordbook_delete_btn: Any
    recent_list: Any
    status_summary: Any
    ocr_menu: Any

    @classmethod
    def capture(cls, source: object) -> "WordInputUiRefs":
        values = {}
        for field in fields(cls):
            source_name = (
                f"_{field.name}" if field.name in {"root_layout", "ocr_menu"} else field.name
            )
            values[field.name] = getattr(source, source_name)
        return cls(**values)


__all__ = ["WordInputUiRefs"]
