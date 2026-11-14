"""Record schema versions and the named migrations between them (design 5.0, 5.2).

Every kind of record has a schema version, kept in the `record_schema` table: a kind with no row is at version 1, the
shape the first builds saved. A migration is a named function from one record's data to the data of the next version of
its kind. When a workspace opens, the migrations its kinds haven't had yet run once, oldest first, in one transaction
with the version bump: a record is rewritten as a new version, every field it changes is a ledger entry under the
migration's own name (`migrate.<name>`, written by the engine, in no changeset so it can't be undone), and each result
must be a valid record of its kind. If one migration fails, or gives a record that isn't valid, nothing is changed and
the workspace doesn't open, with the migration's name in the reason. A new workspace is made at the current versions, so
nothing is run on it, and a workspace saved at a version this program doesn't know is refused rather than misread.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: The version every kind is at until a migration says otherwise.
BASE_VERSION = 1

TABLE = """
CREATE TABLE IF NOT EXISTS record_schema (
    kind   TEXT    PRIMARY KEY,
    schema INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class Migration:
    """One step for one kind of record: `apply` turns the data of a record at version `to_version - 1` into the data
    at `to_version`. `name` is unique and is what the ledger and any failure say."""

    kind: str
    name: str
    to_version: int
    apply: Callable[[dict[str, Any]], dict[str, Any]]


#: Every migration this program knows. A change that renames or removes a field of a record adds its migration here,
#: in the same change.
MIGRATIONS: list[Migration] = []


def latest(kind: str) -> int:
    """The schema version this program writes for a kind of record."""
    return max((m.to_version for m in MIGRATIONS if m.kind == kind), default=BASE_VERSION)


def run(store: Any) -> list[str]:
    """Bring a workspace's records up to this program's schema versions. Returns the names of the migrations run."""
    from engine.storage.store import StoreError

    conn: sqlite3.Connection = store._conn
    conn.execute(TABLE)
    kinds = sorted({m.kind for m in MIGRATIONS})
    with store._lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            done = _run(store, conn, kinds)
        except BaseException as err:
            conn.execute("ROLLBACK")
            if isinstance(err, StoreError):
                raise
            if isinstance(err, Exception):
                raise StoreError(f"The workspace couldn't be brought up to date: {err}") from err
            raise
        conn.execute("COMMIT")
    return done


def _run(store: Any, conn: sqlite3.Connection, kinds: list[str]) -> list[str]:
    from engine.records import REGISTRY
    from engine.storage.store import StoreError, Tx, WriteContext, _validate, dumps

    recorded = {r["kind"]: r["schema"] for r in conn.execute("SELECT kind, schema FROM record_schema")}
    for kind, version in recorded.items():
        if version > latest(kind):
            raise StoreError(
                f"The workspace's {kind} records are saved in format {version}, newer than this program understands "
                f"({latest(kind)}). Upgrade the program before using this workspace."
            )
    if not recorded and not conn.execute("SELECT 1 FROM records LIMIT 1").fetchone():
        # A new workspace holds nothing in an earlier shape: it starts at the current versions.
        for kind in kinds:
            conn.execute("INSERT INTO record_schema(kind, schema) VALUES(?, ?)", (kind, latest(kind)))
        return []
    tx = Tx(conn, store.clock, REGISTRY)
    ran: list[str] = []
    for kind in kinds:
        at = recorded.get(kind, BASE_VERSION)
        steps = sorted((m for m in MIGRATIONS if m.kind == kind and m.to_version > at), key=lambda m: m.to_version)
        for step in steps:
            ctx = WriteContext(actor="engine", trust="trusted", op=f"migrate.{step.name}")
            rows = conn.execute("SELECT id, version, data FROM records WHERE kind=? ORDER BY id", (kind,)).fetchall()
            for row in rows:
                before = json.loads(row["data"])
                try:
                    after = step.apply(dict(before))
                    if kind in REGISTRY:
                        after = _validate(REGISTRY[kind], after)
                except Exception as err:
                    raise StoreError(
                        f"The workspace couldn't be brought up to date: the change '{step.name}' failed on "
                        f"{kind} {row['id']} ({type(err).__name__}: {err}). Nothing was changed."
                    ) from err
                diff = {k: after.get(k) for k in set(after) | set(before) if after.get(k) != before.get(k)}
                if not diff:
                    continue
                version = row["version"] + 1
                conn.execute(
                    "UPDATE records SET version=?, data=? WHERE kind=? AND id=?",
                    (version, dumps(after), kind, row["id"]),
                )
                for field in sorted(diff):
                    tx._log(store.clock(), ctx, kind, row["id"], version, field, before.get(field), after.get(field))
            conn.execute(
                "INSERT INTO record_schema(kind, schema) VALUES(?, ?) ON CONFLICT(kind) DO UPDATE SET schema=?",
                (kind, step.to_version, step.to_version),
            )
            ran.append(step.name)
    return ran
