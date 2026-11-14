"""Delete a workspace and everything the app keeps of it (design 12.4).

Deleting one item keeps its history (the ledger, the readable export and the backups still hold what it said), so this
is the one action that takes the content out: the workspace folder with its database, its own history of changes, the
readable export, the text of what came in, the files, the settings and the private files, and every backup copy of
this workspace in the folders backups go to, finished or not. `plan` lists exactly that, each with how many files and
how much space; `erase` deletes what the plan lists, and only after the person has seen it: it takes the plan's
`token`, a hash of the list, and refuses (deleting nothing) when what would go is no longer what they saw. A place the
app can't remove is reported, never skipped silently, and the rest still goes. What the app can't reach is said too:
the synced folder is shared with another computer, so its files stay until the person removes them.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.backup import _is_unfinished_copy_of, is_copy_of
from engine.config import Config
from engine.storage import StoreError
from engine.workspace import Workspace

#: What each kind of thing in the plan is. The screens and the command say these in words of their own.
WORKSPACE = "workspace"  # an entry of the workspace folder
BACKUP = "backup"  # a finished backup copy of this workspace
UNFINISHED = "unfinished_backup"  # a backup copy that was never finished
SYNCED = "synced_folder"  # the folder kept in step with another computer (stays)


class EraseRefused(StoreError):
    """The workspace can't be deleted: the folder isn't a workspace's own, or the list the person saw has changed."""


@dataclass(frozen=True)
class Item:
    kind: str
    path: str
    name: str  # the entry's own name (the database, .git, data, a backup folder)
    files: int
    bytes: int
    commits: int | None = None  # for the workspace's own history: how many changes it holds, when it can be counted


@dataclass(frozen=True)
class Plan:
    workspace: str  # the workspace folder's path
    name: str  # its name, which the person types to confirm at the command line
    items: list[Item]  # what goes
    stays: list[Item]  # what the app can't remove, said so the person knows
    token: str  # a hash of the list of what goes


@dataclass(frozen=True)
class Result:
    removed: list[str]
    failed: list[tuple[str, str]]  # (path, why it stayed)


def _size(path: Path) -> tuple[int, int]:
    """How many files and bytes are under a path (a file counts as one), without following links."""
    if path.is_symlink() or path.is_file():
        try:
            return 1, path.lstat().st_size
        except OSError:
            return 1, 0
    files = size = 0
    for here, _dirs, names in os.walk(path):
        for name in names:
            files += 1
            with contextlib.suppress(OSError):
                size += (Path(here) / name).lstat().st_size
    return files, size


def _commits(root: Path) -> int | None:
    if not (root / ".git").exists() or shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", "HEAD"], capture_output=True, text=True, timeout=10
        )
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _guard(ws: Workspace) -> Path:
    root = ws.root.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve() or not (root / "config").is_dir():
        raise EraseRefused("That folder isn't a workspace's own, so nothing was deleted.")
    return root


def plan(ws: Workspace, cfg: Config) -> Plan:
    """What deleting this workspace would remove, and what it can't."""
    root = _guard(ws)
    items = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        files, size = _size(entry)
        items.append(
            Item(WORKSPACE, str(entry), entry.name, files, size, _commits(root) if entry.name == ".git" else None)
        )
    seen: set[Path] = set()
    for target in cfg.storage.backups.targets:
        base = Path(target.path).expanduser()
        try:
            real = base.resolve()
        except OSError:
            continue
        if real in seen or not base.is_dir() or real.is_relative_to(root):
            continue
        seen.add(real)
        for folder in sorted(base.iterdir(), key=lambda p: p.name):
            if folder.is_symlink() or not folder.is_dir():
                continue
            kind = (
                BACKUP
                if is_copy_of(folder.name, root.name)
                else UNFINISHED
                if _is_unfinished_copy_of(folder.name, root.name)
                else None
            )
            if kind is not None:
                files, size = _size(folder)
                items.append(Item(kind, str(folder), folder.name, files, size))
    stays = []
    shared = (cfg.storage.sync.folder or "").strip()
    if shared:
        folder = Path(shared).expanduser()
        files, size = _size(folder) if folder.is_dir() else (0, 0)
        stays.append(Item(SYNCED, str(folder), folder.name, files, size))
    return Plan(str(root), root.name, items, stays, _token(items))


def _token(items: list[Item]) -> str:
    listed = json.dumps([[i.kind, i.path] for i in items], separators=(",", ":"))
    return hashlib.sha256(listed.encode()).hexdigest()[:32]


def _remove(path: Path) -> str | None:
    """Remove a file or folder; the reason it stayed, or None."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            errors: list[str] = []

            def note(_func: Callable[..., object], failed: str, exc: BaseException) -> None:
                errors.append(f"{failed}: {exc}")

            shutil.rmtree(path, onexc=note)
            if errors:
                return errors[0]
        return None
    except OSError as err:
        return str(err)


def erase(ws: Workspace, cfg: Config, token: str, *, before: Callable[[], None] | None = None) -> Result:
    """Delete what `plan` lists, for the plan whose `token` the person was shown. `before` runs once the list has been
    checked and just before anything is removed (the running app lets go of its database there). Backups go first, then
    the workspace's own entries, then the folder itself when nothing is left in it."""
    now = plan(ws, cfg)
    if token != now.token:
        raise EraseRefused("What would be deleted has changed since you looked, so nothing was deleted. Look again.")
    if before is not None:
        before()
    removed, failed = [], []
    for item in sorted(now.items, key=lambda i: i.kind == WORKSPACE):
        why = _remove(Path(item.path))
        if why is None:
            removed.append(item.path)
        else:
            failed.append((item.path, why))
    root = Path(now.workspace)
    try:
        root.rmdir()
        removed.append(str(root))
    except FileNotFoundError:
        pass
    except OSError as err:
        if not any(p == str(root) for p, _ in failed):
            failed.append((str(root), str(err)))
    return Result(removed, failed)
