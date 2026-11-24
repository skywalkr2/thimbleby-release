"""What an update does around the install itself (design 11.7, "Updates install what was tested, and come back if they
fail"): for each workspace it serves it takes a copy of the database and notes the version it came from, after the
install it opens the workspace once with the new program (the record migrations run there), and when anything fails it
puts the database back. The program's own version is put back by the caller (`git`, or the kept package), because only
the caller knows how it was installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
    """A copy kept on this computer with the other local copies (`engine/backup.py`), and a consistent copy of the
    workspace's database (one at a time, the latest replacing the one before), with a note of the version the update
    came from. Raises `UpdateError` when it can't be made, so nothing is changed."""
    from engine import backup as copies

    try:
        copies.local_backup_before(ws, now)
    except copies.BackupFirstFailed as err:
        raise UpdateError(str(err)) from None
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
    Returns False when there is no copy to put back. The live database is never missing, at any moment: the copy is
    written whole to a file beside it first, and takes its place in one step. A restore that stops part-way raises
    `UpdateError` and can be run again."""
    copy = backup_database(_folder(ws))
    if not copy.is_file():
        return False
    live = ws.db_path
    incoming = live.with_name(f".{live.name}.restoring")
    try:
        if _same_bytes(copy, live) and not Path(f"{live}-wal").exists():
            return True  # already put back by a run that stopped just after: nothing to keep or replace again
        _copy_whole(copy, incoming)
        if live.exists():
            _keep(live, live.with_name(KEPT))
        # The journal files belong to the database being replaced: read with the copy, they would damage it.
        for extra in ("-wal", "-shm"):
            Path(f"{live}{extra}").unlink(missing_ok=True)
        os.replace(incoming, live)
    except (OSError, sqlite3.Error) as err:
        incoming.unlink(missing_ok=True)
        raise UpdateError(f"The copy made before updating couldn't be put back ({err.__class__.__name__}).") from None
    return True


def _same_bytes(one: Path, other: Path) -> bool:
    if not other.is_file() or one.stat().st_size != other.stat().st_size:
        return False
    with one.open("rb") as a, other.open("rb") as b:
        return hashlib.file_digest(a, "sha256").digest() == hashlib.file_digest(b, "sha256").digest()


def _copy_whole(source: Path, target: Path) -> None:
    """Copy a file under another name and make sure it is on the disk before it is used."""
    with source.open("rb") as read, target.open("wb") as write:
        shutil.copyfileobj(read, write)
        write.flush()
        os.fsync(write.fileno())


def _keep(live: Path, kept: Path) -> None:
    """Keep the database as it is now under another name, whole. What its journal still holds is written into it first,
    so the kept file stands alone; a database that can't be opened is kept as its files are."""
    folded = False
    try:
        conn = sqlite3.connect(live)
        try:
            folded = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        finally:
            conn.close()
    except sqlite3.Error:
        folded = False
    saving = kept.with_name(f".{kept.name}.saving")
    _copy_whole(live, saving)
    journal = Path(f"{live}-wal")
    if folded or not journal.exists():
        if folded:
            for extra in ("-wal", "-shm"):
                Path(f"{kept}{extra}").unlink(missing_ok=True)
    else:
        _copy_whole(journal, Path(f"{kept}-wal"))
    os.replace(saving, kept)
