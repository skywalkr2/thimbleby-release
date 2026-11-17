"""The installed app's own window and its menu-bar or tray item.

One design on both systems: the window is the system's web view (WebKit on the Mac, WebView2 on Windows) showing a
bundled starting page and then the app; the item lists the state and the person's choices. Everything the shell does
to the window or the item goes through `MainThread`, so a call from the server's threads or the menu's own loop never
reaches the system's toolkit from the wrong thread (the Mac stops an app that does).

The toolkits themselves are behind two small interfaces (`WindowBackend`, `TrayBackend`; the real ones are in
`engine/appwindow_backends.py`), so the rules here run, and are tested, with no display."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from engine import startpage

#: The states the menu's top line names, in the words of the app's header chip (wording sheet `desktop.state.*`).
STATES = ("starting", "live", "restart", "restarting", "failed")
#: Schemes a link may be handed to the person's own browser with.
EXTERNAL_SCHEMES = {"http", "https", "mailto"}


class WindowBackend(Protocol):
    """The system's web view window and its main loop."""

    def post(self, call: Callable[[], None]) -> None:
        """Run a call on the loop's thread."""

    def create(
        self, title: str, html: str, api: Any, on_closing: Callable[[], bool], on_quit: Callable[[], None]
    ) -> None:
        """Make the window, hidden, showing a page. on_closing returns False to keep the window (it is hidden).
        on_quit is called when the system's own Quit reaches the window library (the application menu, its shortcut,
        the Dock), which the library reports as a close of the window; it ends the app."""

    def run(self, worker: Callable[[], None]) -> None:
        """Run the loop on this (the main) thread, with the worker on another thread, until the window is destroyed."""

    def show(self) -> None: ...
    def hide(self) -> None: ...
    def load_url(self, url: str) -> None: ...
    def load_html(self, html: str) -> None: ...
    def script(self, code: str) -> None: ...
    def destroy(self) -> None: ...

    def page_state(self) -> dict[str, Any]:
        """The page now in the window: {"address": its address or "", "drawn": whether it shows any text}."""


class TrayBackend(Protocol):
    """The menu-bar or tray item."""

    def start(self, lines: Callable[[], list[MenuLine]], act: Callable[[str], None], title: str) -> None: ...
    def refresh(self) -> None: ...
    def dock(self, shown: bool) -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True)
class MenuLine:
    """One line of the menu: a key the choice is named by, its words, and whether it can be chosen or is ticked."""

    key: str
    text: str
    enabled: bool = True
    checked: bool | None = None
    default: bool = False
    separator_before: bool = False


@dataclass(frozen=True)
class WindowFit:
    """Where and how large the window opens on a screen: size, smallest size and top-left corner, in points."""

    width: int
    height: int
    min_width: int
    min_height: int
    x: int
    y: int


def fit_window(
    screen: tuple[int, int],
    preferred: tuple[int, int] = (1280, 860),
    minimum: tuple[int, int] = (760, 560),
    share: float = 0.9,
) -> WindowFit:
    """The window's size for a screen: the preferred size, but never more than a share of the screen's width and
    height, centred, and with a smallest size that is never larger than the window itself."""
    width = max(1, min(preferred[0], int(screen[0] * share)))
    height = max(1, min(preferred[1], int(screen[1] * share)))
    return WindowFit(
        width,
        height,
        min(minimum[0], width),
        min(minimum[1], height),
        max(0, (screen[0] - width) // 2),
        max(0, (screen[1] - height) // 2),
    )


def _note(words: str) -> None:
    """A line on the app's own error stream (the build machines' checks print it)."""
    with contextlib.suppress(Exception):
        from engine.launcher import note

        note(words)


#: Seconds the window loop has to end after quitting before the process ends itself.
END_GRACE_SECONDS = 10.0


class MainThread:
    """Runs calls on the thread that owns the window loop; a call from any other thread is posted to it."""

    def __init__(self, post: Callable[[Callable[[], None]], None], owner: threading.Thread | None = None):
        self.post = post
        self.owner = owner or threading.current_thread()

    def call(self, function: Callable[..., None], *args: Any) -> None:
        if threading.current_thread() is self.owner:
            function(*args)
        else:
            self.post(lambda: function(*args))


def menu_lines(
    words: Mapping[str, str], system: str, state: str, *, restart_on: bool, login_on: bool
) -> list[MenuLine]:
    """The menu as the person sees it now: the state, then Open, Restart, the login choice, Help and Quit."""
    login = words["desktop.login.mac" if system == "Darwin" else "desktop.login.windows"]
    return [
        MenuLine("state", words[f"desktop.state.{state}"], enabled=False),
        MenuLine("open", words["desktop.open"], default=True, separator_before=True),
        MenuLine("restart", words["desktop.restart"], enabled=restart_on),
        MenuLine("login", login, checked=login_on, separator_before=True),
        MenuLine("help", words["desktop.help"]),
        MenuLine("quit", words["desktop.quit"], separator_before=True),
    ]


def copy_text(text: str, system: str | None = None) -> None:
    """Put text on the system clipboard, with the system's own program."""
    system = system or sys.platform
    command = (
        ["pbcopy"] if system == "darwin" else ["clip"] if system == "win32" else ["xclip", "-selection", "clipboard"]
    )
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            command, input=text.encode("utf-16-le" if system == "win32" else "utf-8"), check=False, timeout=10
        )


def outside_address(url: str) -> bool:
    """Whether a link is one to hand to the person's browser: a web or mail address."""
    return urlsplit(url).scheme.lower() in EXTERNAL_SCHEMES


class PageApi:
    """What the pages in the window may ask of the app (pywebview exposes its public methods to them)."""

    def __init__(self, shell: AppShell):
        self._shell = shell

    def retry(self) -> None:
        self._shell.retry_event.set()

    def copy_details(self) -> None:
        self._shell.copy(self._shell.details)

    def choose(self, answer: str) -> None:
        """The person's answer to the question the starting window asks: "use" or "fresh"."""
        if answer in ("use", "fresh"):
            self._shell.answer = answer
            self._shell.answer_event.set()

    def page_drawn(self) -> None:
        """The app's page says it has drawn: the surest sign there is, since a system web view may not answer a script
        run in it from outside."""
        self._shell.page_drawn = True

    def open_external(self, url: str) -> bool:
        """Open a link to another address in the person's own browser, never in this window."""
        if not isinstance(url, str) or not outside_address(url):
            return False
        self._shell.external(url)
        return True


class AppShell:
    """The window and the item, and the state the menu names. Every method is safe to call from any thread."""

    def __init__(
        self,
        window: WindowBackend,
        tray: TrayBackend | None,
        words: Mapping[str, str],
        *,
        system: str,
        version: str = "",
        copy: Callable[[str], None] = copy_text,
        external: Callable[[str], Any] = webbrowser.open,
        login_on: Callable[[], bool] = lambda: False,
        quiet: bool = False,
    ):
        self.window, self.tray, self.words, self.system, self.version = window, tray, words, system, version
        self.copy, self.external, self.login_on = copy, external, login_on
        #: Started at login: nothing shows until the person opens it from the menu.
        self.quiet = quiet
        self.state = "starting"
        self.details = ""
        self.restart_enabled: Callable[[], bool] = lambda: False
        self.quit_event = threading.Event()
        self.retry_event = threading.Event()
        self.answer = ""
        self.answer_event = threading.Event()
        self.main = MainThread(window.post)
        self._actions: dict[str, Callable[[], None]] = {}
        self._quitting = False
        #: Set when the window loop has returned; the end guard waits for it after the work is done.
        self._ended = threading.Event()
        #: How long the loop has to end once the work is done and the window destroyed, before the process ends itself.
        self.end_grace_seconds = END_GRACE_SECONDS
        self._exit: Callable[[int], None] = os._exit
        self._shown = False
        self._app_loaded = False
        self.page_drawn = False  # set by the app's page itself, through the window's bridge
        self.api = PageApi(self)

    # --- the loop -------------------------------------------------------------------------------------------------

    def run(self, work: Callable[[], int]) -> int:
        """Own this (the main) thread for the window loop and run the work on another; returns the work's result."""
        self.main = MainThread(self.window.post)
        result: list[int] = [1]

        def worker() -> None:
            try:
                self.main.call(self._start_item)
                result[0] = work()
            finally:
                self.main.call(self._finish)

        self.window.create(
            self.words["desktop.title"],
            startpage.page(self.words, self.version),
            self.api,
            self._closing,
            self._quit_requested,
        )
        try:
            self.window.run(worker)
        finally:
            self._ended.set()
        return result[0]

    def _start_item(self) -> None:
        if self.tray is not None:
            self.tray.start(self.lines, self._act, self.words["desktop.title"])

    def _finish(self) -> None:
        _note("the work has stopped; closing the window")
        self._quitting = True
        if self.tray is not None:
            self.tray.stop()
        self.window.destroy()
        threading.Thread(target=self._end_guard, name="end-guard", daemon=True).start()

    def _end_guard(self) -> None:
        """Every Quit ends the app: the work is done by now (the server stopped and the workspace unlocked), so a window
        loop that still hasn't returned after the grace period is ended with the process."""
        if self._ended.wait(self.end_grace_seconds):
            return
        _note(f"the window loop was still running {self.end_grace_seconds} seconds after quitting; ending the app")
        self._exit(0)

    def _closing(self) -> bool:
        """Closing the window leaves the app running in the menu bar or tray: it only hides."""
        if self._quitting:
            return True
        self.main.call(self._hide)
        return False

    def _quit_requested(self) -> None:
        """The system's own Quit (application menu, its shortcut, the Dock) ends the app by the same path as the
        menu-bar item's Quit: the work stops, the server and lock are released, and the loop ends."""
        self.quit()

    # --- what the menu shows and does -----------------------------------------------------------------------------

    def lines(self) -> list[MenuLine]:
        return menu_lines(
            self.words, self.system, self.state, restart_on=self.restart_enabled(), login_on=self.login_on()
        )

    def on(self, key: str, action: Callable[[], None]) -> None:
        self._actions[key] = action

    def _act(self, key: str) -> None:
        """A choice in the menu: quit ends the loop at once, the rest run off the menu's thread."""
        if key == "quit":
            self.quit()
            return
        action = self._actions.get(key)
        if action is not None:
            threading.Thread(target=action, name=f"menu-{key}", daemon=True).start()

    def quit_from_menu(self) -> None:
        """Quit by the path the menu's Quit takes."""
        self._act("quit")

    def set_state(self, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        self.state = state
        if self.tray is not None:
            self.main.call(self.tray.refresh)

    def quit(self) -> None:
        _note("quitting: the work is asked to stop")
        self.quit_event.set()
        self.retry_event.set()
        self.answer_event.set()
        self.main.call(self._hide)

    # --- the window -----------------------------------------------------------------------------------------------

    def _show(self) -> None:
        self._shown = True
        if self.tray is not None:
            self.tray.dock(True)
        self.window.show()

    def _hide(self) -> None:
        self._shown = False
        self.window.hide()
        if self.tray is not None:
            self.tray.dock(False)

    def show_starting(self) -> None:
        """The starting window, at once; nothing at login."""
        if not self.quiet:
            self.main.call(self._show)

    def step(self, done: int) -> None:
        self.main.call(self.window.script, startpage.script_tick(done))

    def show_app(self, url: str) -> None:
        """Turn the window into the app (and show it, unless the app started quietly at login)."""
        self._app_loaded = True
        self.page_drawn = False
        self.main.call(self.window.load_url, url)
        if not self.quiet:
            self.main.call(self._show)

    def window_state(self) -> dict[str, Any]:
        """What the control listener's state answer reports: the menu's state, whether the window is showing, the
        page's address and whether the page has drawn. Asked from the listener's thread, never the window's."""
        try:
            page = self.window.page_state()
        except Exception:
            page = {"address": "", "drawn": False}
        page = {**page, "drawn": bool(page.get("drawn")) or self.page_drawn}
        return {"state": self.state, "shown": self._shown, **page}

    def bring_forward(self, fragment: str = "") -> None:
        """Show the window and put it in front; a fragment (such as "#setup") moves the app to that place."""
        self.quiet = False
        self.main.call(self._show)
        if fragment and self._app_loaded:
            self.main.call(self.window.script, f"location.hash = {fragment!r}")

    def ask_earlier(self, path: str, sides: int, todos: int, people: int, used: str) -> bool | None:
        """Ask in the starting window whether to use the work already on this computer: true for "Use it", false for
        "Start fresh", none when the person quit instead of answering."""
        w = self.words
        facts = w["desktop.earlier.facts"].format(path=path, sides=sides, todos=todos, people=people)
        self.answer, _ = "", self.answer_event.clear()
        self.quiet = False
        self.main.call(self._show)
        self.main.call(
            self.window.script,
            startpage.script_choice(
                w["desktop.earlier.title"],
                w["desktop.earlier.found"].format(used=used),
                facts,
                w["desktop.earlier.text"],
            ),
        )
        self.answer_event.wait()
        if self.quit_event.is_set():
            return None
        self.main.call(
            self.window.script,
            startpage.script_resume(w["desktop.starting.title"], w["desktop.starting.subtitle"]),
        )
        return self.answer == "use"

    def problem(self, kind: str, details: str) -> bool:
        """Turn the window into one message with Try again and Copy details; true when the person chose Try again."""
        self.details = details
        title, text = startpage.message(self.words, kind)
        self.retry_event.clear()
        self.quiet = False
        self.main.call(self._show)
        self.main.call(self.window.script, startpage.script_problem(title, text))
        self.retry_event.wait()
        if self.quit_event.is_set():
            return False
        self.main.call(self.window.load_html, startpage.page(self.words, self.version))
        return True
