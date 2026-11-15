"""A stand-in for the operating system's tray, for freezing the app on a computer with no display. Same names the
launcher uses; the icon runs the setup function in a thread and waits until it is stopped."""

import threading


class MenuItem:
    def __init__(self, text, action, enabled=True, default=False, checked=None):
        self.text, self.action, self.enabled, self.default, self.checked = text, action, enabled, default, checked


class Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


class Icon:
    def __init__(self, name, icon=None, title=None, menu=None):
        self.menu, self.visible, self._done = menu, False, threading.Event()

    def run(self, setup=None):
        if setup:
            threading.Thread(target=setup, args=(self,), daemon=True).start()
        self._done.wait()

    def run_detached(self, setup=None):
        self.visible = True

    def stop(self):
        self._done.set()

    def update_menu(self):
        pass
