from __future__ import annotations

import logging
import os
import sys

from app.core import config


def application_display_name() -> str:
    return getattr(config, "APP_DISPLAY_NAME", config.APP_NAME)


def set_macos_process_name(display_name: str) -> None:
    try:
        from Foundation import NSProcessInfo

        NSProcessInfo.processInfo().setProcessName_(display_name)
    except Exception as exc:  # pragma: no cover - depends on PyObjC/macOS session
        logging.getLogger(__name__).info("macOS process name update skipped: %s", exc)


def prepare_macos_gui_process() -> None:
    if sys.platform != "darwin":
        return

    os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")
    set_macos_process_name(application_display_name())

    try:
        import ctypes

        class ProcessSerialNumber(ctypes.Structure):
            _fields_ = [
                ("highLongOfPSN", ctypes.c_uint32),
                ("lowLongOfPSN", ctypes.c_uint32),
            ]

        psn = ProcessSerialNumber(0, 2)  # kCurrentProcess
        app_services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices"
        )
        app_services.TransformProcessType(ctypes.byref(psn), 1)
        app_services.SetFrontProcess(ctypes.byref(psn))
    except Exception as exc:  # pragma: no cover - macOS integration guard
        logging.getLogger(__name__).info(
            "macOS foreground process promotion skipped: %s", exc
        )


def refresh_macos_application_menu(display_name: str | None = None) -> None:
    if sys.platform != "darwin":
        return

    title = display_name or application_display_name()
    try:
        from AppKit import NSApp

        main_menu = NSApp.mainMenu()
        if main_menu is None:
            return
        app_menu_item = main_menu.itemAtIndex_(0)
        if app_menu_item is not None:
            app_menu_item.setTitle_(title)
            submenu = app_menu_item.submenu()
            if submenu is not None:
                submenu.setTitle_(title)
    except Exception as exc:  # pragma: no cover - AppKit session dependent
        logging.getLogger(__name__).info(
            "macOS app menu title update skipped: %s", exc
        )
