"""System-tray icon backed by pystray, run on a background daemon thread.

All menu callbacks are passed wrapped — the caller is expected to marshal them
back onto the Tk main thread (e.g. via root.after(0, fn)).
"""
from __future__ import annotations

import threading
from typing import Callable

import pystray

import mascot


class Tray:
    def __init__(
        self,
        *,
        title: str,
        on_show: Callable[[], None],
        on_hide: Callable[[], None],
        on_toggle: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle = on_toggle
        image = mascot.build(64)

        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", self._wrap(on_toggle), default=True),
            pystray.MenuItem("Refresh now", self._wrap(on_refresh)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show", self._wrap(on_show)),
            pystray.MenuItem("Hide", self._wrap(on_hide)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._wrap(on_quit)),
        )
        self.icon = pystray.Icon("claude-widget", image, title, menu)
        self._thread: threading.Thread | None = None

    @staticmethod
    def _wrap(fn: Callable[[], None]):
        def _handler(_icon=None, _item=None):
            try:
                fn()
            except Exception:
                pass
        return _handler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
