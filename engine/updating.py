"""What an update does around the install itself (design 11.7, "Updates install what was tested, and come back if they
fail"): for each workspace it serves it takes a copy of the database and notes the version it came from, after the
install it opens the workspace once with the new program (the record migrations run there), and when anything fails it
puts the database back. The program's own version is put back by the caller (`git`, or the kept package), because only
the caller knows how it was installed.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from engine.legacy_names import DB_NAME, OLD_DB_NAME, backup_database
from engine.state_file import write_whole
from engine.workspace import Workspace

NOTE = "update-note.json"
FOLDER = "update-backup"
DATABASE = DB_NAME
#: What a database copied aside by a restore is called.
KEPT = f"{DB_NAME}.failed-update"


class UpdateError(Exception):
    """Something an update couldn't do, in words a person can read."""


def _folder(ws: Workspace) -> Path:
    return ws.private_dir / FOLDER


def note(ws: Workspace) -> dict[str, object] | None:
    """The note an update left: the version it came from, and when. None when there is none."""
    try:
        data = json.loads((_folder(ws) / NOTE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def ensure_closed(ws: Workspace) -> None:
    """Refuses while the app has the workspace open: an update changes the program and the records under it."""
    from engine.storage import Store
    from engine.storage.lease import Lease, LeaseHeld

    store = Store(ws.db_path)
    try:
        lease = Lease(store)
        try:
            lease.acquire()
        except LeaseHeld as err:
            raise UpdateError(f"The app is open, so it wasn't updated. {err}") from None
        lease.release()
    finally:
        store.close()


def backup(ws: Workspace, version: str, now: datetime | None = None) -> Path:
    """A consistent copy of the workspace's database (one at a time, the latest replacing the one before), with a
    note of the version the update came from. Raises `UpdateError` when it can't be made, so nothing is changed."""
    folder = _folder(ws)
    target = folder / DATABASE
    try:
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f".{DATABASE}.saving"
        temporary.unlink(missing_ok=True)
        source = sqlite3.connect(ws.db_path)
        copy = sqlite3.connect(temporary)
        try:
            with copy:
                source.backup(copy)
        finally:
            source.close()
            copy.close()
        os.replace(temporary, target)
        (folder / OLD_DB_NAME).unlink(missing_ok=True)
        stamp = (now or datetime.now(UTC)).isoformat()
        write_whole(folder / NOTE, json.dumps({"version": version, "at": stamp}), mode=0o600)
    except (OSError, sqlite3.Error) as err:
        raise UpdateError(
            f"The copy made before updating couldn't be made ({err.__class__.__name__}), so nothing was changed."
        ) from None
    return target


def check(ws: Workspace) -> None:
    """Open the workspace once with this program, which carries its records forward, and close it. Raises
    `UpdateError` when it can't be opened."""
    from engine.storage import Store, StoreError

    try:
        store = Store(ws.db_path)
    except (StoreError, sqlite3.Error) as err:
        raise UpdateError(f"The workspace couldn't be opened by the new version: {err}") from None
    store.close()


def restore(ws: Workspace) -> bool:
    """Put the database back as the update's copy had it. The database as it is now is kept beside it, never deleted.
    Returns False when there is no copy to put back."""
    copy = backup_database(_folder(ws))
    if not copy.is_file():
        return False
    live = ws.db_path
    try:
        if live.exists():
            os.replace(live, live.with_name(KEPT))
        for extra in ("-wal", "-shm"):
            Path(f"{live}{extra}").unlink(missing_ok=True)
        data = copy.read_bytes()
        write_whole_bytes(live, data)
    except OSError as err:
        raise UpdateError(f"The copy made before updating couldn't be put back ({err.__class__.__name__}).") from None
    return True


def write_whole_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.restoring")
    temporary.write_bytes(data)
    os.replace(temporary, path)
