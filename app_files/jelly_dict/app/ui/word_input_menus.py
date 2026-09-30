from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.widgets.language_menu_item import LanguageMenuItem
from app.ui.word_input_ui_refs import WordInputUiRefs


class MenuPresenter:
    def __init__(
        self,
        facade: QtWidgets.QWidget,
        ui: WordInputUiRefs | None = None,
    ) -> None:
        self._state = facade
        self._signals = facade
        self.ui = ui

    def set_ui(self, ui: WordInputUiRefs) -> None:
        self.ui = ui

    def _ui(self) -> WordInputUiRefs:
        if self.ui is None:
            raise RuntimeError("word input UI is not built")
        return self.ui

    def _build_language_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self._state)
        menu.setObjectName("languageMenu")
        for label, subtitle, value in [
            ("자동 감지", "입력 문자로 영어/일본어를 판단", ""),
            ("English", "네이버 영어사전으로 조회", "en"),
            ("日本語", "네이버 일본어사전으로 조회", "ja"),
        ]:
            action = QtWidgets.QWidgetAction(menu)
            item = LanguageMenuItem(label, subtitle)
            item.clicked.connect(lambda _=False, v=value: self._set_language(v))
            action.setDefaultWidget(item)
            menu.addAction(action)
            self._state._language_actions[value] = action
        menu.aboutToShow.connect(self._sync_language_menu)
        return menu

    def _build_word_list_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self._state)
        menu.setObjectName("languageMenu")
        for label, subtitle, value in [
            ("최근 단어", "최근 조회한 단어 보기", "recent"),
            ("영어 단어장", "저장된 영어 단어 관리", "en"),
            ("일본어 단어장", "저장된 일본어 단어 관리", "ja"),
        ]:
            action = QtWidgets.QWidgetAction(menu)
            item = LanguageMenuItem(label, subtitle)
            item.clicked.connect(lambda _=False, v=value, m=menu: self._open_word_list(v, m))
            action.setDefaultWidget(item)
            menu.addAction(action)
            self._state._word_list_actions[value] = action
        menu.aboutToShow.connect(self._sync_word_list_menu)
        return menu

    def _build_wordbook_sort_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self._state)
        menu.setObjectName("languageMenu")
        for opt, subtitle in [
            ("최신순", "새로 저장한 단어 먼저"),
            ("오래된순", "처음 저장한 단어 먼저"),
            ("가나다순", "단어 이름 기준 정렬"),
        ]:
            action = QtWidgets.QWidgetAction(menu)
            item = LanguageMenuItem(opt, subtitle)
            item.clicked.connect(lambda _=False, o=opt, m=menu: self._select_sort(o, m))
            action.setDefaultWidget(item)
            menu.addAction(action)
            self._state._sort_actions[opt] = action
        menu.aboutToShow.connect(self._sync_sort_menu)
        return menu

    def _select_sort(self, option: str, menu: QtWidgets.QMenu) -> None:
        menu.close()
        self._on_sort_changed(option)

    def _on_sort_changed(self, option: str) -> None:
        self._ui().wordbook_sort_btn.setText(option)
        self._signals.wordbookSortChanged.emit(option)

    def _rebuild_ocr_model_menu(self) -> None:
        """Rebuild on every open so Google Vision availability tracks the
        live API-key state (set/cleared in the settings dialog)."""
        from app.providers import get_provider_registry

        self._state._ocr_menu.clear()
        self._state._ocr_actions.clear()
        registry = get_provider_registry()
        for descriptor in registry.descriptors("ocr", settings_only=True):
            capability = descriptor.capabilities()
            availability = capability.availability_for("en")
            enabled = not descriptor.selection_requires_dependencies or availability != "missing"
            label = descriptor.short_label or descriptor.display_name
            subtitle = (
                descriptor.subtitle_missing
                if availability == "missing"
                else descriptor.subtitle_available
            )
            action = QtWidgets.QWidgetAction(self._state._ocr_menu)
            item = LanguageMenuItem(label, subtitle)
            item.setEnabled(enabled)
            if enabled:
                item.clicked.connect(
                    lambda _=False, n=descriptor.id, lbl=label: self._select_ocr_provider(n, lbl)
                )
            action.setDefaultWidget(item)
            self._state._ocr_menu.addAction(action)
            self._state._ocr_actions[descriptor.id] = action
        self._sync_ocr_menu()

    def _select_ocr_provider(self, name: str, label: str) -> None:
        self._state._ocr_provider = name
        self._ui().ocr_model_btn.setText(label)
        self._state._ocr_menu.close()
        self._signals.ocrProviderChanged.emit(name)

    def set_ocr_provider_label(self, name: str) -> None:
        """Sync the button label with externally-loaded settings."""
        from app.providers import get_provider_registry

        registry = get_provider_registry()
        try:
            descriptor = registry.descriptor("ocr", name)
        except ValueError:
            descriptor = registry.descriptor("ocr", "apple_vision")
        self._state._ocr_provider = descriptor.id
        self._ui().ocr_model_btn.setText(descriptor.short_label or descriptor.display_name)

    def _open_word_list(self, language: str, menu: QtWidgets.QMenu) -> None:
        menu.close()
        self._signals.openWordListRequested.emit(language)

    def _set_language(self, value: str) -> None:
        self._state._forced_language = value
        labels = {"": "자동 감지", "en": "English", "ja": "日本語"}
        self._ui().lang_button.setText(labels.get(value, "자동 감지"))
        menu = self._ui().lang_button.menu()
        if menu is not None:
            menu.close()

    def _sync_language_menu(self) -> None:
        for value, action in self._state._language_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._state._forced_language)

    def _sync_word_list_menu(self) -> None:
        for value, action in self._state._word_list_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._state._list_mode)

    def _sync_sort_menu(self) -> None:
        for value, action in self._state._sort_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._ui().wordbook_sort_btn.text())

    def _sync_ocr_menu(self) -> None:
        for value, action in self._state._ocr_actions.items():
            widget = action.defaultWidget()  # type: ignore[attr-defined]
            if isinstance(widget, LanguageMenuItem):
                widget.set_selected(value == self._state._ocr_provider)

    def _open_recent_entry(self, item: QtWidgets.QListWidgetItem) -> None:
        payload = item.data(QtCore.Qt.UserRole)
        if isinstance(payload, tuple) and len(payload) == 2:
            word, language = payload
            self._signals.recentEntryRequested.emit(str(word), str(language))


__all__ = ["MenuPresenter"]
