"""The real window and menu-bar or tray item behind `engine/appwindow.py`: pywebview for the window (WebKit on the Mac,
WebView2 on Windows), a small native status item through PyObjC on the Mac, and pystray for the Windows tray.

These classes only translate calls; the rules (which thread, what the menu says, what closing does) are in
`appwindow.py` and are tested there. They need a display and run for real only on the systems' own runners.

**Why the Mac's item is not pystray.** pystray's Mac backend builds the menu once, when it is updated, so the state line
and Restart would go stale or need a refresh loop; it draws no template image; and it touches AppKit from whichever
thread calls it. A status item made here, on the window loop's thread, rebuilds its menu each time it opens
(`menuNeedsUpdate:`), is a template image the menu bar tints for light and dark, and shares the one loop that
pywebview already runs. PyObjC is already there for pywebview."""

from __future__ import annotations

import contextlib
import io
import platform
import queue
import sys
import threading
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import Any

from engine import brandmark
from engine.appwindow import AppShell, MenuLine, fit_window

#: The size the window prefers, its smallest size, and the share of a screen it may take (see `fit_window`).
WINDOW_SIZE = (1280, 860)
WINDOW_MINIMUM = (760, 560)
WINDOW_SCREEN_SHARE = 0.9
#: Whether the page in the window shows any text (the start page, the app or a message: a blank white page does not).
DRAWN_SCRIPT = "document.readyState === 'complete' && !!document.body && document.body.innerText.trim().length > 0"
#: The picture of the mark, in pixels: twice the menu bar's size on the Mac, the tray's size on Windows.
MAC_ICON_PIXELS = 44
TRAY_ICON_PIXELS = 64


def primary_screen() -> tuple[int, int] | None:
    """The size, in points, of the screen the window opens on; None when the system does not say."""
    try:
        import webview

        screen = webview.screens[0]
        return (int(screen.width), int(screen.height)) if screen.width > 0 and screen.height > 0 else None
    except Exception:
        return None


#: The window library's function that answers the Mac's application-level Quit (the application menu, its shortcut and
#: the Dock's Quit all reach it) and reports it as a close of each window.
MAC_TERMINATE_HANDLER = "applicationShouldTerminate_"


def asked_by_quit(frame: Any = None) -> bool:
    """Whether the call being answered is the Mac's application-level Quit rather than the window's own close."""
    frame = frame or sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_name == MAC_TERMINATE_HANDLER:
            return True
        frame = frame.f_back
    return False


def _note(words: str) -> None:
    with contextlib.suppress(Exception):
        from engine.launcher import note

        note(words)


def wake_mac_loop() -> None:
    """Post an empty application event, so a stop the app was asked for takes effect now, not at the next input."""
    import AppKit

    event = (
        AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0
        )
    )
    AppKit.NSApp.postEvent_atStart_(event, True)


def closing_handler(
    on_closing: Callable[[], bool], on_quit: Callable[[], None], asked: Callable[[], bool] = asked_by_quit
) -> Callable[[], bool]:
    """The window's closing event: a Quit ends the app and keeps the window until the app ends it; a close hides."""

    def handle() -> bool:
        quitting = asked()
        _note(f"the window library asked to close the window ({'a Quit' if quitting else 'a close'})")
        if quitting:
            on_quit()
            return False
        return on_closing()

    return handle


class WebviewWindow:
    """The window, drawn by the system's web view.

    The web view's own calls (load a page, run a script, show) wait for the page or the window and, on the Mac, for a
    reply that only the window loop's thread can deliver, so a call made on that thread never returns and the page
    stays blank. Every such call is made from one worker thread, in order, never from the loop's thread."""

    def __init__(self, storage: Path | None = None):
        self.storage = storage
        self.window: Any = None
        self.calls: queue.Queue[Callable[[], None]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.worker_lock = threading.Lock()

    def post(self, call: Callable[[], None]) -> None:
        if platform.system() == "Darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(call)
        else:
            call()  # the Windows web view and tray take calls from any thread

    def _later(self, call: Callable[[], None]) -> None:
        """Run a call on the worker thread, after the calls made before it."""
        with self.worker_lock:
            if self.worker is None:

                def drain() -> None:
                    while True:
                        item = self.calls.get()
                        try:
                            item()
                        except Exception as error:
                            print(f"window call failed: {error!r}", file=sys.stderr, flush=True)

                self.worker = threading.Thread(target=drain, name="window-calls", daemon=True)
                self.worker.start()
        self.calls.put(call)

    def create(
        self, title: str, html: str, api: Any, on_closing: Callable[[], bool], on_quit: Callable[[], None]
    ) -> None:
        import webview

        with contextlib.suppress(Exception):  # where the bridge's scripts come from, for the build machines' check
            from webview.util import get_js_dir

            from engine.launcher import note

            scripts = Path(get_js_dir())
            note(f"window scripts at {scripts} (there: {scripts.is_dir() and any(scripts.glob('*.js'))})")
        fit = fit_window(primary_screen() or WINDOW_SIZE, WINDOW_SIZE, WINDOW_MINIMUM, WINDOW_SCREEN_SHARE)
        self.window = webview.create_window(
            title,
            html=html,
            js_api=api,
            hidden=True,
            width=fit.width,
            height=fit.height,
            x=fit.x,
            y=fit.y,
            min_size=(fit.min_width, fit.min_height),
            text_select=True,
        )
        self.window.events.closing += closing_handler(on_closing, on_quit)

    def run(self, worker: Callable[[], None]) -> None:
        import webview

        folder = None
        icon = None
        if self.storage is not None:
            self.storage.mkdir(parents=True, exist_ok=True)
            folder = str(self.storage)
            if platform.system() == "Windows":
                icon = str(brandmark.write_ico(self.storage / "Thimbleby.ico"))
        webview.start(worker, private_mode=False, storage_path=folder, icon=icon)

    def show(self) -> None:
        self._later(self.window.show)

    def hide(self) -> None:
        self._later(self.window.hide)

    def load_url(self, url: str) -> None:
        self._later(lambda: self.window.load_url(url))

    def load_html(self, html: str) -> None:
        self._later(lambda: self.window.load_html(html))

    def script(self, code: str) -> None:
        # A page that is still loading or was replaced answers with an error; a missed tick is not worth stopping for.
        def run() -> None:
            with contextlib.suppress(Exception):
                self.window.evaluate_js(code)

        self._later(run)

    def page_state(self) -> dict[str, Any]:
        """Called from the control listener's thread, which is not the window loop's, so the waits are safe."""
        address, drawn = "", False
        with contextlib.suppress(Exception):
            address = self.window.get_current_url() or ""
        with contextlib.suppress(Exception):
            drawn = bool(self.window.evaluate_js(DRAWN_SCRIPT))
        return {"address": address, "drawn": drawn}

    def destroy(self) -> None:
        self.window.destroy()
        if platform.system() == "Darwin":
            from PyObjCTools import AppHelper

            # Queued after the library's own close, which stops the app when the last window goes; a Mac app stops
            # only on its next event, and a close asked off an event (a Quit) has none to follow it.
            AppHelper.callAfter(wake_mac_loop)


class MacStatusItem:
    """The menu-bar item and the Dock icon, through AppKit, always on the loop's thread."""

    def __init__(self) -> None:
        self.item: Any = None
        self.bar: Any = None
        self.delegate: Any = None
        self.lines: Callable[[], list[MenuLine]] = lambda: []
        self.act: Callable[[str], None] = lambda key: None

    def start(self, lines: Callable[[], list[MenuLine]], act: Callable[[str], None], title: str) -> None:
        import AppKit
        import Foundation

        self.lines, self.act = lines, act
        owner = self

        class Delegate(Foundation.NSObject):
            def menuNeedsUpdate_(self, menu: Any) -> None:
                owner.fill(menu)

            def choose_(self, sender: Any) -> None:
                owner.act(str(sender.representedObject()))

        self.delegate = Delegate.alloc().init()
        self.bar = AppKit.NSStatusBar.systemStatusBar()
        self.item = self.bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        picture = brandmark.render(brandmark.mark_svg(), MAC_ICON_PIXELS, template=True)
        buffer = io.BytesIO()
        picture.save(buffer, "PNG")
        data = Foundation.NSData.dataWithBytes_length_(buffer.getvalue(), len(buffer.getvalue()))
        image = AppKit.NSImage.alloc().initWithData_(data)
        image.setSize_((MAC_ICON_PIXELS / 2, MAC_ICON_PIXELS / 2))
        image.setTemplate_(True)
        self.item.button().setImage_(image)
        self.item.button().setToolTip_(title)
        menu = AppKit.NSMenu.alloc().initWithTitle_(title)
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(self.delegate)
        self.item.setMenu_(menu)
        self.fill(menu)
        self.dock(False)

    def fill(self, menu: Any) -> None:
        import AppKit

        menu.removeAllItems()
        for line in self.lines():
            if line.separator_before:
                menu.addItem_(AppKit.NSMenuItem.separatorItem())
            entry = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(line.text, "choose:", "")
            entry.setTarget_(self.delegate)
            entry.setRepresentedObject_(line.key)
            entry.setEnabled_(line.enabled)
            if line.checked is not None:
                entry.setState_(AppKit.NSOnState if line.checked else AppKit.NSOffState)
            menu.addItem_(entry)

    def refresh(self) -> None:
        if self.item is not None:
            self.fill(self.item.menu())

    def dock(self, shown: bool) -> None:
        import AppKit

        app = AppKit.NSApplication.sharedApplication()
        policy = AppKit.NSApplicationActivationPolicyRegular if shown else AppKit.NSApplicationActivationPolicyAccessory
        app.setActivationPolicy_(policy)
        if shown:
            app.activateIgnoringOtherApps_(True)

    def stop(self) -> None:
        if self.bar is not None and self.item is not None:
            self.bar.removeStatusItem_(self.item)
            self.item = None


def _run_line(act: Callable[[str], None], key: str, icon: Any, item: Any) -> None:
    act(key)


def _is_checked(value: bool, item: Any) -> bool:
    return value


def tray_items(pystray: Any, lines: list[MenuLine], act: Callable[[str], None]) -> Iterator[Any]:
    """The tray menu's items. pystray counts every argument of an action, defaults included, and refuses more than it
    passes (two for an action, one for a check), so the line's own values are bound with `partial`, which it accepts."""
    for line in lines:
        if line.separator_before:
            yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem(
            line.text,
            partial(_run_line, act, line.key),
            enabled=line.enabled,
            checked=None if line.checked is None else partial(_is_checked, line.checked),
            default=line.default,
        )


class PystrayTray:
    """The Windows tray item (and the tray where a desktop has one), drawn in full colour."""

    def __init__(self) -> None:
        self.icon: Any = None

    def start(self, lines: Callable[[], list[MenuLine]], act: Callable[[str], None], title: str) -> None:
        import pystray

        def items() -> Any:
            yield from tray_items(pystray, lines(), act)

        picture = brandmark.render(brandmark.mark_svg(), TRAY_ICON_PIXELS, template=False)
        self.icon = pystray.Icon(title, picture, title, menu=pystray.Menu(items))
        self.icon.run_detached()

    def refresh(self) -> None:
        if self.icon is not None:
            self.icon.update_menu()

    def dock(self, shown: bool) -> None:
        pass

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()
            self.icon = None


def make_shell(
    words: dict[str, str], *, version: str, storage: Path | None, login_on: Callable[[], bool], quiet: bool
) -> AppShell:
    """The shell for this system: the web view window, and the item that fits it."""
    system = platform.system()
    tray = MacStatusItem() if system == "Darwin" else PystrayTray()
    return AppShell(WebviewWindow(storage), tray, words, system=system, version=version, login_on=login_on, quiet=quiet)
