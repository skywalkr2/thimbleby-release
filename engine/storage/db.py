"""The SQLite database: connection settings and schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind     TEXT    NOT NULL,
    id       TEXT    NOT NULL,
    version  INTEGER NOT NULL,
    deleted  INTEGER NOT NULL DEFAULT 0,
    data     TEXT    NOT NULL,
    PRIMARY KEY (kind, id)
);

CREATE TABLE IF NOT EXISTS sequences (
    kind TEXT    PRIMARY KEY,
    next INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT    NOT NULL,
    changeset TEXT,
    request   TEXT,
    op        TEXT    NOT NULL,
    kind      TEXT    NOT NULL,
    record_id TEXT    NOT NULL,
    version   INTEGER NOT NULL,
    field     TEXT,
    before    TEXT,
    after     TEXT,
    actor     TEXT    NOT NULL,
    trust     TEXT    NOT NULL,
    evidence  TEXT
);
CREATE INDEX IF NOT EXISTS ledger_record ON ledger (kind, record_id, version);

CREATE TABLE IF NOT EXISTS leases (
    name      TEXT PRIMARY KEY,
    holder    TEXT NOT NULL,
    host      TEXT NOT NULL,
    heartbeat TEXT NOT NULL,
    expires   TEXT NOT NULL
);
"""


#: The narrow reads of the store (`Tx.marked`, `Tx.requests_in_play`, `Tx.since` on a request, `Tx.find` by a
#: snapshot's key or a run's request) each have an index here whose condition is the read's condition written the same
#: way, and the read names it, so it touches the records it asks for and not every record of the kind. Made when a
#: workspace opens, whatever its age.
MARKED = (
    ("request", "intake"),
    ("request", "changeset"),
    ("request", "auto_closed"),
    ("snapshot", "event"),
    ("snapshot", "set_aside"),
)
#: Records whose value at a path inside a field is true, for a kind where few are: (kind, field, key inside it).
FLAGGED = (("source", "watched", "by_you"),)
INDEXES = {
    **{
        f"marked_{kind}_{field}": f"ON records(kind) WHERE kind='{kind}' AND deleted=0 "
        f"AND json_extract(data, '$.{field}') IS NOT NULL"
        for kind, field in MARKED
    },
    **{
        f"flagged_{kind}_{field}_{key}": f"ON records(kind) WHERE kind='{kind}' AND deleted=0 "
        f"AND json_extract(data, '$.{field}.{key}') = 1"
        for kind, field, key in FLAGGED
    },
    "request_unfinished": "ON records(kind) WHERE kind='request' AND deleted=0 "
    "AND json_extract(data, '$.state') != 'done'",
    "request_asked": "ON records(kind) WHERE kind='request' AND deleted=0 AND json_extract(data, '$.task') = 'ask'",
    "request_created": "ON records(kind, substr(json_extract(data, '$.created_at'), 1, 10)) "
    "WHERE kind='request' AND deleted=0",
    "snapshot_key": "ON records(json_extract(data, '$.source'), json_extract(data, '$.key')) "
    "WHERE kind='snapshot' AND deleted=0",
    # A read of one kind's ledger entries, oldest first, walks that kind's entries only, not the whole ledger.
    "ledger_kind_seq": "ON ledger(kind, seq)",
    # The entries one change wrote (what Undo and a change's card read) are found by the change, not by a walk.
    "ledger_changeset": "ON ledger(changeset) WHERE changeset IS NOT NULL",
    "run_request": "ON records(json_extract(data, '$.request')) WHERE kind='run' AND deleted=0",
}


def _make_indexes(conn: sqlite3.Connection) -> None:
    """Create the indexes that are missing. Looks first, so a workspace that has them all takes no write lock."""
    have = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    for name, definition in INDEXES.items():
        if name not in have:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} {definition}")


def connect(path: Path) -> sqlite3.Connection:
    """Open the workspace database, creating its schema on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    elif version > SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"The database is format {version}, newer than this program understands ({SCHEMA_VERSION}). "
            "Upgrade the program before using this workspace."
        )
    _make_indexes(conn)
    return conn
