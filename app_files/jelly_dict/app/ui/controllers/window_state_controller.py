from __future__ import annotations

import logging
import sys

from PySide6 import QtCore, QtGui, QtWidgets

log = logging.getLogger(__name__)
MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT = 52


class WindowStateController:
    def __init__(self, window: QtWidgets.QMainWindow) -> None:
        self._window = window
        self._macos_titlebar_chrome_applied = False
        self._main_window_hidden_by_shortcut = False
        self._titlebar_drag_origin: QtCore.QPoint | None = None
        self._titlebar_drag_window_origin: QtCore.QPoint | None = None
        self._titlebar_zoom_restore_geometry: QtCore.QRect | None = None

    def handle_platform_surface_event(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.PlatformSurface:
            self.apply_macos_titlebar_chrome()

    def handle_application_event(
        self,
        watched: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> bool:
        app = QtWidgets.QApplication.instance()
        if watched is app and event.type() == QtCore.QEvent.Type.ApplicationActivate:
            QtCore.QTimer.singleShot(0, self.restore_hidden_main_window)
            return False
        if event.type() == QtCore.QEvent.Type.MouseButtonDblClick and isinstance(
            event,
            QtGui.QMouseEvent,
        ):
            widget = watched if isinstance(watched, QtWidgets.QWidget) else None
            if widget is not None and widget.window() is self._window:
                window_pos = self._window.mapFromGlobal(event.globalPosition().toPoint())
                if self._should_handle_titlebar_double_click(event, window_pos):
                    self._clear_titlebar_drag()
                    self._perform_titlebar_zoom()
                    event.accept()
                    return True
        if isinstance(event, QtGui.QMouseEvent):
            widget = watched if isinstance(watched, QtWidgets.QWidget) else None
            if widget is not None and widget.window() is self._window:
                window_pos = self._window.mapFromGlobal(event.globalPosition().toPoint())
                if self._handle_titlebar_drag_event(event, window_pos):
                    return True
        return False

    def handle_show_event(self) -> None:
        self.apply_macos_titlebar_chrome()

    def handle_mouse_double_click(self, event: QtGui.QMouseEvent) -> bool:
        if not self._should_handle_titlebar_double_click(event):
            return False
        self._clear_titlebar_drag()
        self._perform_titlebar_zoom()
        event.accept()
        return True

    def handle_mouse_event(self, event: QtGui.QMouseEvent) -> bool:
        return self._handle_titlebar_drag_event(event)

    def on_application_state_changed(
        self,
        state: QtCore.Qt.ApplicationState,
    ) -> None:
        if state == QtCore.Qt.ApplicationState.ApplicationActive:
            QtCore.QTimer.singleShot(0, self.restore_hidden_main_window)

    def hide_main_window(self) -> None:
        app = QtWidgets.QApplication.instance()
        if (
            sys.platform == "darwin"
            and app is not None
            and app.platformName().lower() == "cocoa"
        ):
            try:
                from AppKit import NSApp

                self._main_window_hidden_by_shortcut = True
                NSApp.hide_(None)
                return
            except Exception as exc:  # pragma: no cover - depends on macOS app session
                log.info("macOS app hide fallback used: %s", exc)
        self._main_window_hidden_by_shortcut = True
        self._window.hide()

    def restore_hidden_main_window(self) -> None:
        # Mission Control/App Expose can trigger activation changes while
        # lookup browser workers are starting. Only restore windows that
        # were actually hidden/minimized; otherwise leave macOS focus alone.
        needs_restore = (
            self._main_window_hidden_by_shortcut
            or self._window.isMinimized()
            or not self._window.isVisible()
        )
        if not needs_restore:
            return

        if self._main_window_hidden_by_shortcut and sys.platform == "darwin":
            app = QtWidgets.QApplication.instance()
            if app is not None and app.platformName().lower() == "cocoa":
                try:
                    from AppKit import NSApp

                    NSApp.unhide_(None)
                except Exception as exc:  # pragma: no cover - depends on macOS app session
                    log.info("macOS app unhide fallback used: %s", exc)

        if self._window.isMinimized():
            self._window.showNormal()
        elif not self._window.isVisible():
            self._window.show()
        if self._window.isVisible():
            self._window.raise_()
            self._window.activateWindow()
        self._main_window_hidden_by_shortcut = False

    def _should_handle_titlebar_double_click(
        self,
        event: QtGui.QMouseEvent,
        window_pos: QtCore.QPoint | None = None,
    ) -> bool:
        if sys.platform != "darwin" or event.button() != QtCore.Qt.LeftButton:
            return False
        y_pos = window_pos.y() if window_pos is not None else event.position().y()
        return 0 <= y_pos <= MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT

    def _should_handle_titlebar_drag(
        self,
        event: QtGui.QMouseEvent,
        window_pos: QtCore.QPoint | None = None,
    ) -> bool:
        if sys.platform != "darwin" or event.button() != QtCore.Qt.LeftButton:
            return False
        y_pos = window_pos.y() if window_pos is not None else event.position().y()
        return 0 <= y_pos <= MACOS_TITLEBAR_DOUBLE_CLICK_HEIGHT

    def _handle_titlebar_drag_event(
        self,
        event: QtGui.QMouseEvent,
        window_pos: QtCore.QPoint | None = None,
    ) -> bool:
        if sys.platform != "darwin":
            return False
        event_type = event.type()
        if event_type == QtCore.QEvent.Type.MouseButtonPress:
            if not self._should_handle_titlebar_drag(event, window_pos):
                self._clear_titlebar_drag()
                return False
            self._titlebar_drag_origin = event.globalPosition().toPoint()
            self._titlebar_drag_window_origin = self._window.frameGeometry().topLeft()
            return False
        if event_type == QtCore.QEvent.Type.MouseMove:
            if self._titlebar_drag_origin is None:
                return False
            if not (event.buttons() & QtCore.Qt.LeftButton):
                self._clear_titlebar_drag()
                return False
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._titlebar_drag_origin
            if delta.manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return False
            window_handle = self._window.windowHandle()
            if window_handle is not None and window_handle.startSystemMove():
                self._clear_titlebar_drag()
                event.accept()
                return True
            if self._titlebar_drag_window_origin is not None:
                self._window.move(self._titlebar_drag_window_origin + delta)
                event.accept()
                return True
        if event_type == QtCore.QEvent.Type.MouseButtonRelease:
            self._clear_titlebar_drag()
            return False
        return False

    def _clear_titlebar_drag(self) -> None:
        self._titlebar_drag_origin = None
        self._titlebar_drag_window_origin = None

    def _perform_titlebar_zoom(self) -> None:
        app = QtWidgets.QApplication.instance()
        if self._restore_titlebar_zoom_geometry():
            return
        if (
            sys.platform == "darwin"
            and app is not None
            and app.platformName().lower() == "cocoa"
        ):
            try:
                import ctypes
                import objc

                ns_view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self._window.winId())))
                ns_window = ns_view.window()
                if ns_window is not None:
                    if ns_window.isZoomed():
                        ns_window.performZoom_(None)
                        return
                    self._titlebar_zoom_restore_geometry = QtCore.QRect(
                        self._window.geometry()
                    )
                    ns_window.performZoom_(None)
                    return
            except Exception as exc:  # pragma: no cover - depends on macOS window server
                log.info("macOS titlebar zoom fallback used: %s", exc)
        if self._window.isMaximized():
            self._window.showNormal()
            return
        self._titlebar_zoom_restore_geometry = QtCore.QRect(self._window.geometry())
        self._window.showMaximized()

    def _restore_titlebar_zoom_geometry(self) -> bool:
        restore_geometry = self._titlebar_zoom_restore_geometry
        if restore_geometry is None or restore_geometry.isNull():
            self._titlebar_zoom_restore_geometry = None
            return False
        self._titlebar_zoom_restore_geometry = None
        self._window.showNormal()
        self._window.setGeometry(restore_geometry)
        return True

    def apply_macos_titlebar_chrome(self) -> None:
        if self._macos_titlebar_chrome_applied or sys.platform != "darwin":
            return
        app = QtWidgets.QApplication.instance()
        if app is not None and app.platformName().lower() != "cocoa":
            return
        try:
            import ctypes
            import objc
            from AppKit import (
                NSColor,
                NSMaxYEdge,
                NSTitlebarSeparatorStyleNone,
                NSWindowStyleMaskFullSizeContentView,
                NSWindowTitleHidden,
            )

            ns_view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self._window.winId())))
            ns_window = ns_view.window()
            if ns_window is None:
                QtCore.QTimer.singleShot(0, self.apply_macos_titlebar_chrome)
                return
            ns_window.setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    27 / 255,
                    27 / 255,
                    26 / 255,
                    1,
                )
            )
            ns_window.setTitleVisibility_(NSWindowTitleHidden)
            ns_window.setTitlebarAppearsTransparent_(True)
            ns_window.setStyleMask_(
                ns_window.styleMask() | NSWindowStyleMaskFullSizeContentView
            )
            ns_window.setTitlebarSeparatorStyle_(NSTitlebarSeparatorStyleNone)
            ns_window.setAutorecalculatesContentBorderThickness_forEdge_(
                False,
                NSMaxYEdge,
            )
            ns_window.setContentBorderThickness_forEdge_(0, NSMaxYEdge)
            ns_window.setMovableByWindowBackground_(True)
            self._macos_titlebar_chrome_applied = True
        except Exception as exc:  # pragma: no cover - depends on macOS window server
            log.info("macOS titlebar chrome update skipped: %s", exc)
