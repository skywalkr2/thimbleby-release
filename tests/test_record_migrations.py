"""A workspace saved by an earlier build opens and stays editable (design 5.0, 5.2): records have a schema version for
each kind, named migrations run once when a workspace opens, and each change they make is in the ledger. The workspace
used here is `tests/fixtures/earlier_build/workspace.sqlite`, made by the build before migrations existed; the earlier
build's field name is simulated by renaming a field inside it."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from engine.storage import InvalidRecord, Store, StoreError, WriteContext
from engine.storage import migrations as m
from engine.workspace import init_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "earlier_build" / "workspace.sqlite"
PERSON = "PER-2"
_EDIT = WriteContext(actor="pm", trust="trusted", op="record.set")


def rename_back(path: Path) -> None:
    """Put the fixture's people in the shape an earlier build saved them in: `full_name` was `display_name`."""
    conn = sqlite3.connect(path)
    for rid, data in conn.execute("SELECT id, data FROM records WHERE kind='person'").fetchall():
        found = json.loads(data)
        found["display_name"] = found.pop("full_name")
        conn.execute("UPDATE records SET data=? WHERE kind='person' AND id=?", (json.dumps(found), rid))
    conn.commit()
    conn.close()


def earlier_workspace(tmp_path: Path):
    ws = init_workspace(tmp_path / "ws", git=False)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{ws.db_path}{suffix}").unlink(missing_ok=True)
    shutil.copy(FIXTURE, ws.db_path)
    rename_back(ws.db_path)
    return ws


def rename_display_name(data: dict) -> dict:
    data = dict(data)
    data["full_name"] = data.pop("display_name")
    return data


@pytest.fixture
def renamed(monkeypatch):
    """A build in which people's `display_name` became `full_name`, and its migration."""
    calls: list[str] = []

    def apply(data: dict) -> dict:
        calls.append(data["id"])
        return rename_display_name(data)

    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration("person", "rename-display-name", 2, apply)])
    return calls


def edit_role(store: Store) -> None:
    with store.transaction() as tx:
        found = tx.get("person", PERSON)
        tx.update("person", PERSON, {"role": "Proofreader"}, _EDIT, read_version=found.version)


def test_without_a_migration_a_renamed_field_leaves_the_record_uneditable(tmp_path):
    store = Store(earlier_workspace(tmp_path).db_path)
    with pytest.raises(InvalidRecord):
        edit_role(store)
    store.close()


def test_opening_the_workspace_runs_the_migration_once_and_the_record_can_be_edited_and_saved(tmp_path, renamed):
    ws = earlier_workspace(tmp_path)
    store = Store(ws.db_path)
    try:
        found = store.read().get("person", PERSON)
        assert found.data["full_name"] == "Second Fixture" and "display_name" not in found.data
        assert found.version == 2  # a rewrite is a new version of the record
        edit_role(store)
        assert store.read().get("person", PERSON).data["role"] == "Proofreader"
        assert sorted(renamed) == ["PER-1", "PER-2", "PER-3"]
        # each change is in the ledger, under the migration's own name
        entries = [
            e for e in store.read().ledger(kind="person", record_id=PERSON) if e["op"] == "migrate.rename-display-name"
        ]
        assert {(e["field"], e["before"], e["after"]) for e in entries} == {
            ("display_name", "Second Fixture", None),
            ("full_name", None, "Second Fixture"),
        }
        assert all(e["actor"] == "engine" and e["changeset"] is None for e in entries)
        assert store.read().sql("SELECT schema FROM record_schema WHERE kind='person'").fetchone()["schema"] == 2
    finally:
        store.close()
    again = Store(ws.db_path)  # opened again: nothing runs twice
    try:
        assert sorted(renamed) == ["PER-1", "PER-2", "PER-3"]
        assert again.read().get("person", PERSON).version == 3
    finally:
        again.close()


def test_a_migration_that_fails_changes_nothing_and_the_workspace_says_why(tmp_path, monkeypatch):
    def broken(data: dict) -> dict:
        if data["id"] == "PER-3":
            raise KeyError("nothing to rename")
        return rename_display_name(data)

    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration("person", "rename-display-name", 2, broken)])
    ws = earlier_workspace(tmp_path)
    with pytest.raises(StoreError, match="rename-display-name"):
        Store(ws.db_path)
    conn = sqlite3.connect(ws.db_path)
    assert all("display_name" in json.loads(d) for (d,) in conn.execute("SELECT data FROM records WHERE kind='person'"))
    assert conn.execute("SELECT count(*) FROM ledger WHERE op LIKE 'migrate.%'").fetchone()[0] == 0
    conn.close()


def test_a_migration_whose_result_is_not_a_valid_record_stops_the_opening_and_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration("person", "wrong", 2, lambda data: {**data, "unknown_field": 1})])
    ws = earlier_workspace(tmp_path)
    with pytest.raises(StoreError, match="wrong"):
        Store(ws.db_path)
    conn = sqlite3.connect(ws.db_path)
    assert conn.execute("SELECT count(*) FROM ledger WHERE op LIKE 'migrate.%'").fetchone()[0] == 0
    conn.close()


def test_a_new_workspace_is_made_at_the_current_version_and_nothing_is_migrated(tmp_path, renamed):
    ws = init_workspace(tmp_path / "fresh", git=False)
    store = Store(ws.db_path)
    try:
        assert renamed == []
        assert store.read().sql("SELECT schema FROM record_schema WHERE kind='person'").fetchone()["schema"] == 2
        assert not [e for e in store.read().ledger() if e["op"].startswith("migrate.")]
    finally:
        store.close()
    Store(ws.db_path).close()
    assert renamed == []


def test_a_workspace_from_a_newer_program_is_refused_rather_than_misread(tmp_path, renamed):
    ws = earlier_workspace(tmp_path)
    Store(ws.db_path).close()
    conn = sqlite3.connect(ws.db_path)
    conn.execute("UPDATE record_schema SET schema=9 WHERE kind='person'")
    conn.commit()
    conn.close()
    with pytest.raises(StoreError, match="newer"):
        Store(ws.db_path)


def test_migrations_for_one_kind_run_in_order_and_each_is_recorded_once(tmp_path, monkeypatch):
    order: list[str] = []

    def second(data: dict) -> dict:
        order.append("second")
        return {**data, "role": (data.get("role") or "") + "!"}

    def first(data: dict) -> dict:
        order.append("first")
        return rename_display_name(data)

    monkeypatch.setattr(
        m, "MIGRATIONS", [m.Migration("person", "later", 3, second), m.Migration("person", "earlier", 2, first)]
    )
    ws = earlier_workspace(tmp_path)
    store = Store(ws.db_path)
    try:
        assert order == ["first"] * 3 + ["second"] * 3
        assert store.read().get("person", PERSON).data["role"] == "Printer!"
        ops = [e["op"] for e in store.read().ledger(kind="person", record_id=PERSON) if e["op"].startswith("migrate.")]
        assert ops.index("migrate.earlier") < ops.index("migrate.later")
    finally:
        store.close()
