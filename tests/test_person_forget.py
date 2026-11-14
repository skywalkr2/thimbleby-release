"""Forgetting a person (design 5.2, 12.4; S-0443 part 1): the record, the ledger and earlier changes, the export and its
git history, the synced folder, Undo, the assistant, and the route."""

import shutil
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient

from engine.applier import Context, Inputs, apply_as_person, check
from engine.names import People
from engine.ops import CHANGESET
from engine.people_forget import BLANKED, FORGOTTEN_NAME
from engine.storage import Store
from engine.storage.export import commit_export, export_data, history_problem, rebuild_history
from tests.test_handover import set_folder, write

NAME = "Marlowe Quillfeather"
FIRST = "Marly"
ALIAS = "The ropewalker"
ROLE = "Ropewalk inspector"
NOTE = "Keeps the tide chart nobody else reads"
EMAIL = "marlowe.quillfeather@example.com"
LATER_ROLE = "Retired ropewalk inspector"
VALUES = [NAME, FIRST, ALIAS, ROLE, NOTE, EMAIL, LATER_ROLE]

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git isn't installed")


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


def _export_text(ws) -> str:
    return "".join(p.read_text() for p in sorted(ws.data_dir.rglob("*")) if p.is_file())


def _git(ws, *args):
    return subprocess.run(["git", "-C", str(ws.root), *args], check=True, capture_output=True, text=True).stdout


def _made(client, api, ws, cfg):
    """A person with every kind of detail, then edited so earlier values exist in the ledger and in a change."""
    made = client.post(
        f"{api}/people",
        json={
            "full_name": NAME,
            "first_name": FIRST,
            "aliases": [ALIAS],
            "role": ROLE,
            "how_to_reach": {"email": [EMAIL]},
        },
    )
    assert made.status_code == 200, made.text
    pid = made.json()["id"]
    store = Store(ws.db_path, cfg=cfg)
    try:
        version = store.read().get("person", pid).version
        apply_as_person(
            store,
            cfg,
            [
                {
                    "op": "record.edit",
                    "record": {"kind": "person", "id": pid},
                    "fields": {"why_they_matter": NOTE},
                    "read_version": version,
                }
            ],
            f"Noted why {NAME} matters",
        )
    finally:
        store.close()
    assert client.post(f"{api}/people/{pid}", json={"role": LATER_ROLE}).status_code == 200
    return pid


def _version(client, api, pid):
    return next(p for p in client.get(f"{api}/people").json() if p["id"] == pid), client.get(
        f"{api}/record-pages/{pid}", params={"kind": "person"}
    ).json()["version"]


def _forget(client, api, pid, version):
    return client.post(f"{api}/records/person/{pid}/forget", json={"read_version": version})


def test_forgetting_blanks_the_record_the_ledger_and_earlier_changes_and_keeps_the_id(env):
    client, api, ws, cfg = _client(env)
    pid = _made(client, api, ws, cfg)
    stored = _everything_stored(ws)
    assert all(v in stored for v in VALUES), "every value is held before the forget"
    row, version = _version(client, api, pid)
    done = _forget(client, api, pid, version)
    assert done.status_code == 200 and done.json()["refused"] is None, done.text
    stored = _everything_stored(ws)
    for value in VALUES:
        assert value not in stored, f"{value!r} is still in the database"
    after, _ = _version(client, api, pid)
    assert after["name"] == FORGOTTEN_NAME and after["forgotten_on"]
    assert not after["aliases"] and not after["role"] and not after["how_to_reach"] and not after["first_name"]
    store = Store(ws.db_path, cfg=cfg)
    try:
        record = store.read().get("person", pid)
        assert record is not None and not record.deleted and record.data["forgotten_on"]
        assert {k: record.data[k] for k in BLANKED} == BLANKED
        rows = store.read().ledger(kind="person", record_id=pid)
        assert any(r["op"].startswith("person.forget") for r in rows), "the forget is the redaction's own record"
        changesets = [c for c in store.read().list("changeset")]
        assert not any(NAME in repr(c.data) for c in changesets)
    finally:
        store.close()


def test_the_export_and_its_git_history_hold_none_of_their_values(env):
    client, api, ws, cfg = _client(env)
    pid = _made(client, api, ws, cfg)
    store = Store(ws.db_path, cfg=cfg)
    export_data(store, ws.data_dir)
    store.close()
    commit_export(ws.root, "Export")
    _, version = _version(client, api, pid)
    client.post(f"{api}/people/{pid}", json={"role": ROLE})  # a later commit holds another earlier value
    store = Store(ws.db_path, cfg=cfg)
    export_data(store, ws.data_dir)
    store.close()
    commit_export(ws.root, "Export again")
    assert NAME in _git(ws, "log", "-p", "--all") and int(_git(ws, "rev-list", "--all", "--count")) > 1
    _git(ws, "tag", "old-state")
    _git(ws, "branch", "side")

    _, version = _version(client, api, pid)
    assert _forget(client, api, pid, version).json()["refused"] is None
    assert NAME not in _export_text(ws) and EMAIL not in _export_text(ws)
    history = _git(ws, "log", "-p", "--all")
    for value in VALUES:
        assert value not in history, f"{value!r} is still in the git history"
    assert int(_git(ws, "rev-list", "--all", "--count")) == 1
    assert _git(ws, "tag").strip() == "" and _git(ws, "branch", "--format=%(refname:short)").split() == [
        _git(ws, "symbolic-ref", "--short", "HEAD").strip()
    ]
    assert _git(ws, "reflog").count("\n") <= 1
    assert _git(ws, "status", "--porcelain", "--", "config", "data", "plugin-data").strip() == ""


@needs_git
def test_a_workspace_with_a_remote_refuses_the_rebuild_and_nothing_is_forgotten(env):
    client, api, ws, cfg = _client(env)
    pid = _made(client, api, ws, cfg)
    _git(ws, "remote", "add", "origin", str(ws.root.parent / "elsewhere"))
    assert history_problem(ws.root)
    _, version = _version(client, api, pid)
    done = _forget(client, api, pid, version)
    assert done.status_code == 200 and done.json()["changeset"] is None
    assert done.json()["refused"] == "history" and done.json()["reason"]
    assert NAME in _everything_stored(ws), "a refused forget changes nothing"
    with pytest.raises(Exception, match="copied"):
        rebuild_history(ws.root, "Export")


def test_a_workspace_with_no_git_history_forgets_and_writes_the_export_again(tmp_path, demo):
    from engine.workspace import init_workspace

    ws = init_workspace(tmp_path / "plain", template=demo, git=False)
    cfg = ws.config(env={})
    Store(ws.db_path, cfg=cfg).close()
    client, api, ws, cfg = _client((ws, cfg, Store(ws.db_path, cfg=cfg)))
    pid = _made(client, api, ws, cfg)
    store = Store(ws.db_path, cfg=cfg)
    export_data(store, ws.data_dir)
    store.close()
    assert NAME in _export_text(ws) and not (ws.root / ".git").exists()
    _, version = _version(client, api, pid)
    assert _forget(client, api, pid, version).json()["refused"] is None
    assert NAME not in _export_text(ws) and NAME not in _everything_stored(ws)
    assert not (ws.root / ".git").exists() and rebuild_history(ws.root, "Export") is False


def test_a_file_forget_rebuilds_the_history_too_and_refuses_with_a_remote(env):
    from tests.test_files import _upload

    client, api, ws, cfg = _client(env)
    made = _upload(client, api, "harbor-minutes.png", "Minutes of the private harbor visit")
    store = Store(ws.db_path, cfg=cfg)
    export_data(store, ws.data_dir)
    store.close()
    commit_export(ws.root, "Export")
    _git(ws, "remote", "add", "origin", str(ws.root.parent / "elsewhere"))
    refused = client.post(f"{api}/files/{made['id']}/forget", json={"read_version": made["version"]})
    assert refused.status_code == 409 and "copied" in refused.text
    assert "harbor-minutes.png" in _everything_stored(ws)
    _git(ws, "remote", "remove", "origin")
    done = client.post(f"{api}/files/{made['id']}/forget", json={"read_version": made["version"]})
    assert done.status_code == 200 and done.json()["refused"] is None
    assert "harbor-minutes.png" not in _git(ws, "log", "-p", "--all")
    assert int(_git(ws, "rev-list", "--all", "--count")) == 1


def test_undo_of_an_earlier_change_to_a_forgotten_person_is_refused_and_the_forget_has_no_undo(env):
    client, api, ws, cfg = _client(env)
    pid = _made(client, api, ws, cfg)
    store = Store(ws.db_path, cfg=cfg)
    try:
        earlier = [c for c in store.read().list("changeset") if c.data["summary"] == "Changed on screen"]
    finally:
        store.close()
    assert earlier
    _, version = _version(client, api, pid)
    done = _forget(client, api, pid, version).json()
    for changeset in (earlier[-1].id, done["changeset"]):
        report = client.post(f"{api}/changesets/{changeset}/undo", json={"ops": None})
        assert report.status_code == 200 and report.json()["restored"] == []
        assert "forgotten, not restored" in report.json()["skipped"][0]["reason"]
    assert LATER_ROLE not in _everything_stored(ws) and NAME not in _everything_stored(ws)
    assert _version(client, api, pid)[0]["name"] == FORGOTTEN_NAME


def test_the_assistant_cannot_forget_a_person(env):
    ws, cfg, store = env
    person = next(p for p in store.read().list("person") if p.id != cfg.workspace.user.person)
    op = {"op": "person.forget", "person": person.id, "read_version": person.version}
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
    assert store.read().get("person", person.id).data["full_name"] == person.data["full_name"]


def test_the_route_refuses_what_cannot_be_forgotten_and_an_edit_after_a_forget(env):
    client, api, ws, cfg = _client(env)
    pid = _made(client, api, ws, cfg)
    _, version = _version(client, api, pid)
    assert _forget(client, api, "PER-404", 1).status_code == 404
    assert _forget(client, api, pid, version + 1).json() == {"changeset": None, "refused": "changed", "reason": None}
    me = cfg.workspace.user.person
    assert _forget(client, api, me, 1).json()["refused"] == "you"
    assert NAME in _everything_stored(ws)
    assert _forget(client, api, pid, version).json()["refused"] is None
    assert _forget(client, api, pid, version).json()["refused"] == "forgotten"
    edited = client.post(f"{api}/people/{pid}", json={"role": ROLE})
    assert edited.status_code == 409 and "forgotten" in edited.text
    assert ROLE not in _everything_stored(ws)
    store = Store(ws.db_path, cfg=cfg)
    try:
        refused = store.read().get("person", pid)
        assert refused.data["full_name"] == FORGOTTEN_NAME
    finally:
        store.close()


def test_a_forget_on_one_computer_is_replayed_on_the_other_with_no_divergence(tmp_path):
    from engine.handover import _folder_ledger, _local_ledger, compare, open_workspace, release
    from engine.people_forget import forget_person
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B

    folder = tmp_path / "synced"
    folder.mkdir()
    a = init_workspace(tmp_path / "a", template=DEMO_B, git=False)
    b = init_workspace(tmp_path / "b", git=False, personal=False)
    cfg_a, cfg_b = set_folder(a, folder), set_folder(b, folder)
    open_workspace(a, cfg_a)
    store = Store(a.db_path, cfg=cfg_a)
    apply_as_person(
        store, cfg_a, [{"op": "person.add", "full_name": NAME, "role": ROLE, "aliases": [ALIAS]}], f"Added {NAME}"
    )
    pid = next(p.id for p in store.read().list("person") if p.data["full_name"] == NAME)
    store.close()
    write(a, cfg_a)
    release(a, cfg_a)
    assert open_workspace(b, cfg_b).action == "loaded"
    assert NAME in _everything_stored(b), "the second computer holds them before the forget"
    release(b, cfg_b)

    assert open_workspace(a, cfg_a).action in ("same", "newer_here")
    store = Store(a.db_path, cfg=cfg_a)
    try:
        forget_person(a, store, cfg_a, pid, read_version=store.read().get("person", pid).version, summary="Forgot")
    finally:
        store.close()
    write(a, cfg_a)
    release(a, cfg_a)

    opened = open_workspace(b, cfg_b)
    assert opened.action == "loaded"
    for value in (NAME, ROLE, ALIAS):
        assert value not in repr(_local_ledger(b)) and value not in _everything_stored(b)
    assert compare(_local_ledger(b), _folder_ledger(folder)) == "same"
    assert compare(_local_ledger(b), _local_ledger(a)) == "same"


def test_the_applier_refuses_every_kind_of_change_to_a_forgotten_person(env):
    client, api, ws, cfg = _client(env)
    pid = _made(client, api, ws, cfg)
    _, version = _version(client, api, pid)
    assert _forget(client, api, pid, version).json()["refused"] is None
    store = Store(ws.db_path, cfg=cfg)
    try:
        held = store.read().get("person", pid)
        ops = [
            {"op": "record.edit", "record": {"kind": "person", "id": pid}, "fields": {"role": ROLE}, "read_version": 9},
            {"op": "record.set", "kind": "person", "id": pid, "field": "role", "value": ROLE},
            {"op": "person.stance", "id": pid, "stance": "watch"},
            {"op": "person.forget", "person": pid, "read_version": held.version},
        ]
        for op in ops[:3]:
            cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
            ctx = Context(
                store,
                cfg,
                People(store, cfg),
                tuple(store.plugins.ops),
                Inputs("REQ-1", None, "", "", "trusted"),
                actor="pm",
            )
            found = [p for p in check(cs, ctx) if p.severity == "refuse"]
            assert found and "forgotten" in found[0].message, op
        with pytest.raises(Exception, match="forgotten already"):
            apply_as_person(store, cfg, [ops[3]], "Again")
    finally:
        store.close()
