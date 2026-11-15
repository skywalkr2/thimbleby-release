"""A stand-in for the system's web view window, for freezing the app on a computer with no display. Same names the
app's window uses; the loop runs the start function in a thread and waits until the window is destroyed."""

import threading


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _Events:
    closing = None

    def __init__(self):
        self.closing = _Event()


class Window:
    def __init__(self, title, html=None, **options):
        self.title, self.html, self.options = title, html, options
        self.events = _Events()
        self.url = None
        self.gone = threading.Event()

    def show(self):
        pass

    def hide(self):
        pass

    def load_url(self, url):
        self.url = url

    def load_html(self, html):
        self.html = html

    def evaluate_js(self, code):
        return None

    def destroy(self):
        self.gone.set()


_windows = []


def create_window(title, html=None, **options):
    window = Window(title, html, **options)
    _windows.append(window)
    return window


def start(func=None, **options):
    if func:
        threading.Thread(target=func, daemon=True).start()
    for window in _windows:
        window.gone.wait()
