"""A workspace made by the command-line version, found on the first run of the installed app.

The installed app keeps its workspace in the app-data place. A person who used the command-line version has one in
their home folder (or wherever it was last started). The first run finds it, says what it holds, and the person
chooses: bring it in (a copy, the original stays as it was) or start fresh (the original is not touched). Nothing here
changes, moves or deletes the original."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from engine.legacy_names import DB_NAME, OLD_DB_NAME, OLD_PRIVATE_DIR, PRIVATE_DIR, db_file

#: What is never copied: the files that stay on one computer (the sign-in token, the instance lock) and the
#: database, which is copied by the database's own backup.
_SKIPPED = {
    PRIVATE_DIR,
    OLD_PRIVATE_DIR,
    f"{DB_NAME}-wal",
    f"{DB_NAME}-shm",
    f"{OLD_DB_NAME}-wal",
    f"{OLD_DB_NAME}-shm",
}


@dataclass(frozen=True)
class Found:
    path: Path
    sides: int
    todos: int
    people: int


def _holds_work(path: Path) -> bool:
    return (path / "config").is_dir() and db_file(path).is_file()


def candidates(home: Path) -> list[Path]:
    """The places an earlier workspace may be: the one started last, then the default folders in the home folder."""
    from engine.cli import default_workspace, last_workspace

    named = [last_workspace(), default_workspace(home)]
    seen: list[Path] = []
    for path in named:
        if path is not None and path not in seen:
            seen.append(path)
    return seen


def counts(path: Path) -> tuple[int, int, int]:
    """Sides (top-level projects), to-dos and people the workspace holds, read without changing it."""
    uri = f"file:{db_file(path)}?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return 0, 0, 0
    try:

        def number(kind: str, extra: str = "") -> int:
            query = f"SELECT COUNT(*) FROM records WHERE kind = ? AND deleted = 0 {extra}"
            return int(db.execute(query, (kind,)).fetchone()[0])

        top = "AND COALESCE(json_extract(data, '$.parent'), '') = ''"
        return number("project", top), number("action"), number("person")
    except sqlite3.Error:
        return 0, 0, 0
    finally:
        db.close()


def find(home: Path, own: Path) -> Found | None:
    """The earlier workspace on this computer, when there is one that is not the installed app's own and holds work."""
    own = own.expanduser().resolve()
    for path in candidates(home):
        if path.resolve() != own and _holds_work(path):
            return Found(path, *counts(path))
    return None


def bring_in(source: Path, target: Path) -> None:
    """Copy the earlier workspace to `target` (which does not exist yet). The database is copied through the database's
    own backup, so a copy made while the old app runs is whole. The original is only read."""

    def skip(folder: str, names: list[str]) -> set[str]:
        return {n for n in names if n in _SKIPPED or n == db_file(source).name} if Path(folder) == source else set()

    shutil.copytree(source, target, ignore=skip, dirs_exist_ok=True)
    reading = sqlite3.connect(f"file:{db_file(source)}?mode=ro", uri=True)
    writing = sqlite3.connect(target / db_file(source).name)
    try:
        reading.backup(writing)
    finally:
        writing.close()
        reading.close()
