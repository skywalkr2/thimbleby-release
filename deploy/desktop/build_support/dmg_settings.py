"""What the disk image looks like: its volume name, its window, where its two icons sit and the two lines it says.

The window is laid out by `dmgbuild`, which writes the Finder's own window settings file directly (no Finder scripting,
so it does not depend on a logged-in desktop). The background pictures are drawn at build time by
`engine.installer_art`."""

from __future__ import annotations

from pathlib import Path

from engine import installer_art

#: The two lines under the icons.
LINES = ("Drag Thimbleby into Applications", "Then open it from Applications or Launchpad")
WINDOW_POSITION = (200, 120)


def volume_name(version: str) -> str:
    return f"Thimbleby {version}"


def settings(app_name: str, background: Path) -> dict:
    """The `dmgbuild` settings for a disk image holding the application bundle `app_name` and an alias to
    Applications; `background` is the 1x picture (its `@2x` sibling is found beside it)."""
    return {
        "format": "UDZO",
        "background": str(background),
        "window_rect": (WINDOW_POSITION, installer_art.DMG_WINDOW),
        "default_view": "icon-view",
        "icon_size": installer_art.DMG_ICON_SIZE,
        "text_size": 13,
        "show_status_bar": False,
        "show_tab_view": False,
        "show_toolbar": False,
        "show_pathbar": False,
        "show_sidebar": False,
        "symlinks": {"Applications": "/Applications"},
        "icon_locations": {
            app_name: installer_art.DMG_APP_CENTER,
            "Applications": installer_art.DMG_APPLICATIONS_CENTER,
        },
    }
