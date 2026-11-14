"""Removing a file and forgetting its stored copy (design 5.3, 12.4; S-0019): the bytes, the ledger, Undo, the synced
folder, the assistant, and the route."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from engine.actions import ACTION_CORE_OPS
from engine.applier import Context, Inputs, check
from engine.files import FORGET_FIELDS, add_file, blob_path
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.storage.export import export_data
from tests.test_files import PNG, _upload
from tests.test_handover import set_folder, write

NAME = "harbor-minutes.png"
SECRET = "Minutes of the private harbor visit"


@pytest.fixture
def env(workspace):
    cfg = workspace.config(env={})
    store = Store(workspace.db_path, cfg=cfg)
    yield workspace, cfg, store
    store.close()


def _client(env):
    from api.app import create_app

    ws, cfg, store = env
    store.close()
    client = TestClient(create_app(ws, cfg, "test-token", start_worker=False))
    client.headers["Authorization"] = "Bearer test-token"
    return client, cfg.server.base_path.rstrip("/") + "/api", ws, cfg


def _everything_stored(ws) -> str:
    """Every ledger row and record of the workspace as one text, to look for what must be gone."""
    conn = sqlite3.connect(ws.db_path)
    try:
        rows = conn.execute("SELECT * FROM ledger").fetchall() + conn.execute("SELECT * FROM records").fetchall()
    finally:
        conn.close()
    return repr(rows)


def _blobs(ws):
    return [p for p in (ws.root / "files").rglob("*") if p.is_file()]


def _forget(client, api, made):
    return client.post(f"{api}/files/{made['id']}/forget", json={"read_version": made["version"]})


def test_forgetting_deletes_the_bytes_and_the_export_but_leaves_a_blob_another_file_shares(env):
    client, api, ws, _ = _client(env)
    first = _upload(client, api, NAME, SECRET)
    twin = _upload(client, api, "twin.png", "Same bytes")  # the same bytes, so one stored copy
    other = _upload(client, api, "other.png", "Other bytes", PNG + b"\x07")
    assert len(_blobs(ws)) == 2
    # The readable export holds the file's name and details until the next write refreshes it.
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    export_data(store, ws.data_dir)
    store.close()
    assert NAME in "".join(p.read_text() for p in ws.data_dir.glob("*.json"))

    done = _forget(client, api, first)
    assert done.status_code == 200 and done.json()["refused"] is None, done.text
    assert len(_blobs(ws)) == 2, "the twin still holds the copy"
    assert client.get(f"{api}/files/{twin['id']}/content").content == PNG
    assert NAME not in "".join(p.read_text() for p in ws.data_dir.glob("*.json"))
    assert NAME not in _everything_stored(ws) and SECRET not in _everything_stored(ws)

    assert _forget(client, api, twin).status_code == 200
    assert [p.read_bytes() for p in _blobs(ws)] == [PNG + b"\x07"], "no copy of the forgotten bytes is left"
    assert "twin.png" not in "".join(p.read_text() for p in ws.data_dir.glob("*.json"))
    assert [f["id"] for f in client.get(f"{api}/files").json()] == [other["id"]]


def test_the_ledger_gives_up_the_earlier_values_of_the_files_descriptive_fields(env):
    client, api, ws, _ = _client(env)
    made = _upload(client, api, NAME, SECRET)
    assert NAME in _everything_stored(ws)
    assert _forget(client, api, made).status_code == 200
    conn = sqlite3.connect(ws.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM ledger WHERE kind='file' AND record_id=?", (made["id"],)).fetchall()
    conn.close()
    assert rows and {r["field"] for r in rows if r["field"]} >= {"name", "sha256", "meta"}
    for row in rows:
        if row["field"] in FORGET_FIELDS:
            assert row["before"] in (None, "null") and row["after"] in (None, "null"), dict(row)
    assert any(r["op"].startswith("file.forget") for r in rows), "the forget is the redaction's own record"
    assert NAME not in _everything_stored(ws) and SECRET not in _everything_stored(ws)


def test_undo_of_an_earlier_edit_never_brings_a_forgotten_value_back_and_the_forget_has_no_undo(env):
    client, api, ws, cfg = _client(env)
    made = _upload(client, api, NAME, SECRET)
    edited = client.post(
        f"{api}/files/{made['id']}/edit", json={"read_version": made["version"], "name": "renamed.png"}
    )
    now = client.get(f"{api}/files").json()[0]
    done = _forget(client, api, now)
    assert done.status_code == 200, done.text
    for changeset in (edited.json()["changeset"], done.json()["changeset"]):
        report = client.post(f"{api}/changesets/{changeset}/undo", json={"ops": None})
        assert report.status_code == 200 and report.json()["restored"] == []
        assert "forgotten, not restored" in report.json()["skipped"][0]["reason"]
    assert client.get(f"{api}/files").json() == []
    store = Store(ws.db_path, cfg=cfg)
    try:
        record = store.read().get("file", made["id"], include_deleted=True)
        assert record.deleted and record.data["name"] == "" and record.data["sha256"] == ""
    finally:
        store.close()
    assert "renamed.png" not in _everything_stored(ws) and NAME not in _everything_stored(ws)
    assert client.post(f"{api}/changesets/{done.json()['changeset']}/undo", json={"ops": None}).status_code == 200
    assert _blobs(ws) == []


def test_the_assistant_cannot_forget_a_file(env):
    ws, cfg, store = env
    file = add_file(store, cfg, PNG, name=NAME, media_type="image/png")
    op = {"op": "file.forget", "file": file.id, "read_version": file.version}
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})

    def refused(actor):
        ctx = Context(
            store,
            cfg,
            People(store, cfg),
            tuple(store.plugins.ops),
            Inputs("REQ-1", None, "", "", "trusted"),
            actor=actor,
        )
        return [p.check for p in check(cs, ctx) if p.severity == "refuse"]

    assert refused("assistant") == ["person-only"]
    assert refused("pm") == []
    assert blob_path(store, file.data["sha256"]).is_file() and store.read().get("file", file.id) is not None
    assert "file.forget" not in ACTION_CORE_OPS, "a plugin's action never offers it either"


def test_the_route_refuses_a_stale_version_and_a_file_another_record_refers_to(env):
    client, api, ws, _ = _client(env)
    first = _upload(client, api, NAME, SECRET)
    newer = _upload(client, api, "cover-2.png", "Second", PNG + b"\x01", f"&replaces={first['id']}")
    assert _forget(client, api, first).json() == {"changeset": None, "refused": "referred_to"}
    stale = client.post(f"{api}/files/{newer['id']}/forget", json={"read_version": newer["version"] + 1})
    assert stale.json() == {"changeset": None, "refused": "changed"}
    assert client.post(f"{api}/files/FILE-404/forget", json={"read_version": 1}).status_code == 404
    assert len(client.get(f"{api}/files").json()) == 2 and len(_blobs(ws)) == 2
    assert NAME in _everything_stored(ws)


def test_a_forget_on_one_computer_is_replayed_on_the_other_with_no_divergence(tmp_path):
    from engine.handover import _folder_ledger, _local_ledger, compare, open_workspace, release
    from engine.sync import MACHINE
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B

    folder = tmp_path / "synced"
    folder.mkdir()
    a = init_workspace(tmp_path / "a", template=DEMO_B, git=False)
    b = init_workspace(tmp_path / "b", git=False, personal=False)
    cfg_a, cfg_b = set_folder(a, folder), set_folder(b, folder)
    open_workspace(a, cfg_a)
    store = Store(a.db_path, cfg=cfg_a)
    kept = add_file(store, cfg_a, b"words nobody else holds", name=NAME, media_type="text/plain")
    other = add_file(store, cfg_a, b"words that stay", name="stays.txt", media_type="text/plain")
    digest = kept.data["sha256"]
    store.close()
    write(a, cfg_a)
    release(a, cfg_a)
    assert open_workspace(b, cfg_b).action == "loaded"
    release(b, cfg_b)
    from engine.files import blob_path_in

    assert blob_path_in(b.root, digest).is_file(), "the second computer has its own copy"

    assert open_workspace(a, cfg_a).action in ("same", "newer_here")
    from engine.files import forget_file

    store = Store(a.db_path, cfg=cfg_a)
    try:
        forget_file(a, store, cfg_a, kept.id, read_version=kept.version, summary="Forgot a file")
    finally:
        store.close()
    write(a, cfg_a)
    release(a, cfg_a)
    assert not (folder / MACHINE / "files" / digest).exists(), "the folder lost the blob at the next write"
    assert (folder / MACHINE / "files" / other.data["sha256"]).is_file()
    assert not blob_path_in(a.root, digest).exists()

    opened = open_workspace(b, cfg_b)
    assert opened.action == "loaded"
    assert not blob_path_in(b.root, digest).exists(), "the loading computer deleted its own copy"
    assert blob_path_in(b.root, other.data["sha256"]).is_file()
    assert NAME not in repr(_local_ledger(b)) and NAME not in _everything_stored(b)
    assert compare(_local_ledger(b), _folder_ledger(folder)) == "same"
    assert compare(_local_ledger(b), _local_ledger(a)) == "same"
