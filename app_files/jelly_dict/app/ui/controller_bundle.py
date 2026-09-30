"""Composition of MainWindow controllers without changing the widget contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.app_container import AppContainer
from app.ui.controllers.browser_prewarm_controller import BrowserPrewarmController
from app.ui.controllers.export_controller import ExportController
from app.ui.controllers.lookup_queue_controller import LookupQueueController
from app.ui.controllers.lookup_suggestion_dialog import confirm_lookup_suggestion
from app.ui.controllers.ocr_controller import OcrController
from app.ui.controllers.recent_controller import RecentController
from app.ui.controllers.save_controller import SaveController
from app.ui.controllers.saved_words_cache_controller import SavedWordsCacheController
from app.ui.controllers.tts_background_controller import TtsBackgroundController
from app.ui.controllers.wordbook_controller import WordbookController


class _ControllerLinks:
    """Typed callback relay for the small controller dependency cycle.

    The relay exists before any controller and is bound once after construction,
    replacing lambdas that dereferenced MainWindow attributes which did not yet
    exist.
    """

    def __init__(self) -> None:
        self.lookup_queue: LookupQueueController | None = None
        self.recent: RecentController | None = None
        self.saved_words: SavedWordsCacheController | None = None

    def bind(
        self,
        lookup_queue: LookupQueueController,
        recent: RecentController,
        saved_words: SavedWordsCacheController,
    ) -> None:
        self.lookup_queue = lookup_queue
        self.recent = recent
        self.saved_words = saved_words

    def abort_lookup_queue(self) -> None:
        self._lookup_queue().abort()

    def schedule_next_lookup(self) -> None:
        self._lookup_queue().schedule_next()

    def preview_cancelled(self) -> None:
        self._lookup_queue().preview_cancelled()

    def start_saved_words_cache_load(self) -> None:
        controller = self.saved_words
        if controller is None:
            raise RuntimeError("saved-word controller is not bound")
        controller.start()

    def refresh_recent(self, remember: bool) -> None:
        controller = self.recent
        if controller is None:
            raise RuntimeError("recent controller is not bound")
        controller.refresh(remember=remember)

    def refresh_recent_if_visible(self) -> None:
        controller = self.recent
        if controller is None:
            raise RuntimeError("recent controller is not bound")
        controller.refresh_if_visible()

    def _lookup_queue(self) -> LookupQueueController:
        controller = self.lookup_queue
        if controller is None:
            raise RuntimeError("lookup queue controller is not bound")
        return controller


@dataclass(frozen=True)
class ControllerBundle:
    tts_background: TtsBackgroundController
    browser_prewarm: BrowserPrewarmController
    export: ExportController
    save: SaveController
    lookup_queue: LookupQueueController
    ocr: OcrController
    wordbook: WordbookController
    recent: RecentController
    saved_words_cache: SavedWordsCacheController

    def reconfigure_from_container(self, container: AppContainer) -> None:
        self.ocr.update_provider(container.ocr_provider)
        self.lookup_queue.update_lookup_service(container.lookup_service)
        self.save.update_save_service(container.save_service)
        self.export.update_settings(container.settings, container.export_service)
        self.wordbook.update_settings(
            container.settings,
            container.anki_sync,
            container.lookup_service,
        )


def build_main_window_controllers(
    window: Any,
    container: AppContainer,
    startup_perf,
) -> ControllerBundle:
    """Build, bind, and connect every controller used by MainWindow."""
    links = _ControllerLinks()
    tts_background = TtsBackgroundController(window)
    browser_prewarm = BrowserPrewarmController(
        window,
        container.current_provider,
        startup_perf,
    )
    export = ExportController(
        window,
        container.settings,
        container.export_service,
        container.export_capabilities,
        settings_store=container.settings_store,
        settings_committer=container.reconfigure_and_save,
    )
    export.settingsRequested.connect(window._open_settings)
    save = SaveController(
        parent=window,
        input_view=window.input_view,
        preview_view=window.preview_view,
        stack=window.stack,
        input_page=window._input_page,
        preview_page=window._preview_page,
        save_service=container.save_service,
        settings_getter=container.current_settings,
        status_bar=window.status,
        abort_lookup_queue=links.abort_lookup_queue,
        schedule_next_lookup=links.schedule_next_lookup,
        start_saved_words_cache_load=links.start_saved_words_cache_load,
        queue_tts_pre_generation=window._queue_tts_pre_generation,
        refresh_recent=links.refresh_recent,
        preview_cancelled=links.preview_cancelled,
        commit_saved_projection=window._commit_saved_projection,
    )
    lookup_queue = LookupQueueController(
        parent=window,
        input_view=window.input_view,
        status_bar=window.status,
        lookup_service=container.lookup_service,
        manual_provider=container.manual_provider,
        present_entry=save.present_entry,
        confirm_suggestion=lambda typed, suggestion, detected_language: confirm_lookup_suggestion(
            window,
            typed,
            suggestion,
            detected_language,
        ),
        return_to_input=save.return_to_input,
        refresh_recent_if_visible=links.refresh_recent_if_visible,
    )
    ocr = OcrController(
        parent=window,
        input_view=window.input_view,
        status_bar=window.status,
        provider=container.ocr_provider,
    )
    wordbook = WordbookController(
        window,
        window.input_view,
        container.cache,
        container.anki_sync,
        container.settings,
        window.status,
        lookup_service=container.lookup_service,
        queue_tts_pre_generation=window._queue_tts_pre_generation,
        remember_last_view_mode=window._remember_last_view_mode,
        workbook_repository=container.workbook_repository,
        wordbook_service=container.wordbook_service,
    )
    recent = RecentController(
        window,
        window.input_view,
        container.cache,
        wordbook,
        window.status,
        window._remember_last_view_mode,
        window.show_undo_toast,
    )
    saved_words_cache = SavedWordsCacheController(
        window,
        container.current_settings,
        window.input_view,
        wordbook,
        links.refresh_recent_if_visible,
        startup_perf,
        container.workbook_repository,
    )
    links.bind(lookup_queue, recent, saved_words_cache)

    window.input_view.submitted.connect(lookup_queue.submit)
    window.input_view.bulkSubmitted.connect(lookup_queue.submit_bulk)
    window.input_view.jobCancelRequested.connect(lookup_queue.cancel_job)
    window.input_view.jobRetryRequested.connect(lookup_queue.retry_job)
    window.input_view.bulkRetryFailedRequested.connect(lookup_queue.retry_failed)
    window.input_view.bulkClearFailedRequested.connect(lookup_queue.clear_failed)
    window.input_view.lookupStopRequested.connect(lookup_queue.stop)
    window.input_view.ocrBatchSubmitted.connect(lookup_queue.submit_ocr_batch)
    window.input_view.ocrBulkLookupRequested.connect(lookup_queue.submit_ocr_bulk)
    window.input_view.clearRecentRequested.connect(recent.clear)
    if hasattr(window.input_view, "prewarmRequested"):
        window.input_view.prewarmRequested.connect(browser_prewarm.schedule)
    window.input_view.imageOpenRequested.connect(ocr.open_image)
    window.input_view.imageDropped.connect(ocr.start_for_path)
    window.input_view.clipboardImagePasted.connect(ocr.start_for_clipboard_image)
    window.input_view.ocrCleared.connect(ocr.cleanup_current_temp)
    window.preview_view.saveRequested.connect(save.preview_save)
    window.preview_view.cancelled.connect(save.preview_cancelled)

    bundle = ControllerBundle(
        tts_background,
        browser_prewarm,
        export,
        save,
        lookup_queue,
        ocr,
        wordbook,
        recent,
        saved_words_cache,
    )
    container.add_reconfigure_listener(bundle.reconfigure_from_container)
    return bundle
