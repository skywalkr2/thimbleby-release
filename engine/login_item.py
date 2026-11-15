"""Starting the app when the person signs in to the computer: the Mac's launch agent and the Windows run key.

The app is started with `--at-login`, which opens it quietly (no window until the person opens it from the item).
Nothing is set up until the person turns it on; turning it off removes exactly what turning it on made."""

from __future__ import annotations

import contextlib
import plistlib
import sys
from collections.abc import Sequence
from pathlib import Path

AT_LOGIN_FLAG = "--at-login"
#: The launch agent's label on the Mac (the app's bundle id) and the value's name in the Windows run key.
MAC_LABEL = "app.thimbleby.desktop"
WINDOWS_VALUE = "Thimbleby"
WINDOWS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command(executable: str | None = None) -> list[str]:
    """What the system runs at sign-in: this program, told it was started at login."""
    return [executable or sys.executable, AT_LOGIN_FLAG]


def mac_agent_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def is_enabled(system: str, home: Path | None = None) -> bool:
    if system == "Darwin":
        return mac_agent_path(home or Path.home()).is_file()
    if system == "Windows":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_KEY) as key:
                winreg.QueryValueEx(key, WINDOWS_VALUE)
            return True
        except OSError:
            return False
    return False


def set_enabled(system: str, enabled: bool, home: Path | None = None, program: Sequence[str] | None = None) -> None:
    arguments = list(program) if program else command()
    if system == "Darwin":
        path = mac_agent_path(home or Path.home())
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(plistlib.dumps({"Label": MAC_LABEL, "ProgramArguments": arguments, "RunAtLoad": True}))
        else:
            path.unlink(missing_ok=True)
    elif system == "Windows":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WINDOWS_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, WINDOWS_VALUE, 0, winreg.REG_SZ, " ".join(f'"{a}"' for a in arguments))
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, WINDOWS_VALUE)


def toggle(system: str, home: Path | None = None) -> bool:
    """Flip the choice; the new state."""
    now = not is_enabled(system, home)
    set_enabled(system, now, home)
    return now
