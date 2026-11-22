"""Opening a kept file with the computer's own program for it, from the installed app's window.

The window (a system web view) ignores downloads and pop-ups, so the page asks the app to hand the file over. The app
opens only a file this workspace keeps (a record of kind `file`, its bytes checked against their hash), saves it first
under the workspace's private folder (a folder that never leaves this computer, never a shared one), and hands that copy
to the computer's default program, but only for a document or media kind: its name's last ending (which decides even
when the stored type claims otherwise) and its stored media type must both be on the lists in `storage.files`. Any
other kind (a program, a script, a shortcut) is never started: it is shown in its folder. Anything that is not a kept
file is refused. Programs are started by injected functions, so tests start nothing."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.files import read_bytes
from engine.storage import StoreError

#: The folder inside the private folder that holds the copies handed to the computer's programs.
FOLDER = "opened"
#: What `open_kept` did: the file was opened, or it was only shown in its folder (a kind that is never started).
OPENED, SHOWN = "opened", "shown"
_ID = re.compile(r"FILE-\d+")
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_name(name: str) -> str:
    """A file name that can only be a name: no folders, no characters a system refuses, never empty or a dot."""
    cleaned = _UNSAFE.sub("_", Path(str(name)).name).strip(" .")
    return cleaned or "file"


def start_program(path: Path, system: str | None = None) -> None:
    """Hand a file to the computer's default program for it."""
    system = system or sys.platform
    if system == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        return
    subprocess.Popen(["open" if system == "darwin" else "xdg-open", str(path)])  # noqa: S603


def show_in_folder(path: Path, system: str | None = None) -> None:
    """Show a file in its folder, without starting it."""
    system = system or sys.platform
    if system == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603, S607
    elif system == "darwin":
        subprocess.Popen(["open", "-R", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])  # noqa: S603, S607


def may_open(name: str, media_type: str, extensions: list[str], types: list[str]) -> bool:
    """Whether a file of this name and stored type is a kind to start: its last ending and its type are both listed."""
    ending = Path(_safe_name(name)).suffix.lower().lstrip(".")
    return (
        bool(ending)
        and ending in {e.lower().lstrip(".") for e in extensions}
        and media_type.lower() in {t.lower() for t in types}
    )


def open_kept(
    store: Any,
    private_dir: Path,
    file_id: object,
    start: Callable[[Path], Any] = start_program,
    show: Callable[[Path], Any] = show_in_folder,
    *,
    extensions: list[str] | None = None,
    types: list[str] | None = None,
) -> str | None:
    """Save the kept file `file_id` under the private folder and open it with the computer's program (`OPENED`), or only
    show it in its folder when it isn't a kind to start (`SHOWN`). None, with nothing saved or started, for
    anything that isn't the id of a file this workspace keeps. The lists default to the workspace's settings."""
    if not isinstance(file_id, str) or not _ID.fullmatch(file_id):
        return None
    try:
        record, data = read_bytes(store, file_id)
    except (StoreError, OSError):
        return None
    if extensions is None or types is None:
        cfg = getattr(getattr(store, "plugins", None), "cfg", None)
        limits = cfg.storage.files if cfg is not None else None
        extensions = extensions if extensions is not None else (limits.open_extensions if limits else [])
        types = types if types is not None else (limits.open_types if limits else [])
    target = Path(private_dir) / FOLDER / file_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / _safe_name(record.data["name"])
    path.write_bytes(data)
    if may_open(record.data["name"], str(record.data["media_type"]), extensions, types):
        start(path)
        return OPENED
    show(path)
    return SHOWN
