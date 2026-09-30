"""One-release compatibility facade for role-focused word-input parts."""

from app.ui.word_input_parts.chips import OcrCandidateChip, QueueJobChip
from app.ui.word_input_parts.flow_layout import FlowLayout
from app.ui.word_input_parts.labels_buttons import (
    ElideLabel,
    MenuTextButton,
    RightClickFilter,
    _repolish,
    _resource_icon,
)
from app.ui.word_input_parts.layout_constants import (
    HERO_TO_WORDBOOK_SPACING,
    NORMAL_LIST_HEIGHT,
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    RESOURCE_DIR,
    ROOT_LAYOUT_SPACING,
    ROOT_MARGIN_EXPANDED,
    ROOT_MARGIN_NORMAL,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
)
from app.ui.word_input_parts.spinner import LoadingSpinner
from app.ui.word_input_parts.text_parsing import (
    BULK_INPUT_SPLIT_RE,
    _compact_detection_status,
    _elide,
    split_bulk_input,
)
from app.ui.word_input_parts.wordbook_list import WordbookListWidget

__all__ = [
    "BULK_INPUT_SPLIT_RE",
    "ElideLabel",
    "FlowLayout",
    "HERO_TO_WORDBOOK_SPACING",
    "LoadingSpinner",
    "MenuTextButton",
    "NORMAL_LIST_HEIGHT",
    "OcrCandidateChip",
    "QueueJobChip",
    "RECENT_EMPTY_TEXT",
    "RECENT_FILTER_EMPTY_TEXT",
    "RESOURCE_DIR",
    "ROOT_LAYOUT_SPACING",
    "ROOT_MARGIN_EXPANDED",
    "ROOT_MARGIN_NORMAL",
    "RightClickFilter",
    "WORDBOOK_EMPTY_TEXT",
    "WORDBOOK_FILTER_EMPTY_TEXT",
    "WordbookListWidget",
    "_compact_detection_status",
    "_elide",
    "_repolish",
    "_resource_icon",
    "split_bulk_input",
]
