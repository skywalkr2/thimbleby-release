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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine import brandmark
from engine.appwindow import AppShell, MenuLine

WINDOW_SIZE = (1280, 860)
WINDOW_MINIMUM = (760, 560)
#: The picture of the mark, in pixels: twice the menu bar's size on the Mac, the tray's size on Windows.
MAC_ICON_PIXELS = 44
TRAY_ICON_PIXELS = 64


class WebviewWindow:
    """The window, drawn by the system's web view."""

    def __init__(self, storage: Path | None = None):
        self.storage = storage
        self.window: Any = None

    def post(self, call: Callable[[], None]) -> None:
        if platform.system() == "Darwin":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(call)
        else:
            call()  # the Windows web view and tray take calls from any thread

    def create(self, title: str, html: str, api: Any, on_closing: Callable[[], bool]) -> None:
        import webview

        self.window = webview.create_window(
            title,
            html=html,
            js_api=api,
            hidden=True,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=WINDOW_MINIMUM,
            text_select=True,
        )
        self.window.events.closing += on_closing

    def run(self, worker: Callable[[], None]) -> None:
        import webview

        folder = None
        if self.storage is not None:
            self.storage.mkdir(parents=True, exist_ok=True)
            folder = str(self.storage)
        webview.start(worker, private_mode=False, storage_path=folder)

    def show(self) -> None:
        self.window.show()

    def hide(self) -> None:
        self.window.hide()

    def load_url(self, url: str) -> None:
        self.window.load_url(url)

    def load_html(self, html: str) -> None:
        self.window.load_html(html)

    def script(self, code: str) -> None:
        # A page that is still loading or was replaced answers with an error; a missed tick is not worth stopping for.
        with contextlib.suppress(Exception):
            self.window.evaluate_js(code)

    def destroy(self) -> None:
        self.window.destroy()


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


class PystrayTray:
    """The Windows tray item (and the tray where a desktop has one), drawn in full colour."""

    def __init__(self) -> None:
        self.icon: Any = None

    def start(self, lines: Callable[[], list[MenuLine]], act: Callable[[str], None], title: str) -> None:
        import pystray

        def items() -> Any:
            for line in lines():
                if line.separator_before:
                    yield pystray.Menu.SEPARATOR
                checked = None if line.checked is None else (lambda item, value=line.checked: value)
                yield pystray.MenuItem(
                    line.text,
                    lambda icon, item, key=line.key: act(key),
                    enabled=line.enabled,
                    checked=checked,
                    default=line.default,
                )

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
