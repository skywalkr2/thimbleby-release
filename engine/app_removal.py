"""Removing the installed app from a Mac, which has no uninstaller: the card in Settings explains it, opens the folder
the work stays in, and quits the app after showing it in Finder, ready to drag to the Bin.

Nothing here deletes anything: the app is dragged by the person, and the work's folder is only opened."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from engine.app_dirs import app_dirs
from engine.legacy_names import app_name

Runner = Callable[[list[str]], object]


@dataclass(frozen=True)
class Removal:
    """Whether the card shows (the installed app on a Mac), the app's folder and the folder the work stays in."""

    available: bool
    app: Path | None
    folder: Path | None


def app_bundle(executable: str | Path) -> Path | None:
    """The `.app` folder a program inside a Mac app is in, or none when it is not inside one."""
    for parent in Path(executable).parents:
        if parent.suffix == ".app":
            return parent
    return None


def plan(
    system: str,
    executable: str | Path,
    frozen: bool,
    env: Mapping[str, str],
    home: Path,
) -> Removal:
    """The card is for the installed app on a Mac: a program run from source, or another system, shows none."""
    bundle = app_bundle(executable) if frozen and system == "Darwin" else None
    if bundle is None:
        return Removal(False, None, None)
    return Removal(True, bundle, Path(app_dirs(system, env, home, app_name(system, env, home)).data))


def current(env: Mapping[str, str], home: Path) -> Removal:
    import platform

    return plan(platform.system(), sys.executable, bool(getattr(sys, "frozen", False)), env, home)


def _run(command: list[str]) -> object:
    return subprocess.run(command, check=False, timeout=15)


def open_folder(removal: Removal, run: Runner | None = None) -> bool:
    """Show the work's folder in Finder. False when this is not the installed Mac app or the folder is not there."""
    if not removal.available or removal.folder is None or not removal.folder.is_dir():
        return False
    (run or _run)(["open", str(removal.folder)])
    return True


def show_app(removal: Removal, run: Runner | None = None) -> bool:
    """Show the app in Finder, selected in its folder. False when this is not the installed Mac app."""
    if not removal.available or removal.app is None:
        return False
    (run or _run)(["open", "-R", str(removal.app)])
    return True
