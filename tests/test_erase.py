"""Delete a workspace and its backups (design 12.4): one action lists exactly what goes and, once the person has seen
it, takes the content out of the workspace folder, its history and every backup copy of this workspace. Deleting one
item keeps its history; this is what removes it. Other workspaces' backups, a backup folder itself and the synced folder
stay."""

from pathlib import Path

import pytest

from engine import backup, erase
from engine.cli import main
from engine.config.yaml_edit import set_key
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

NAME = "thimbleby"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / NAME, template=DEMO_B)
    offsite = tmp_path / "offsite"
    offsite.mkdir()
    synced = tmp_path / "synced"
    synced.mkdir()
    (synced / "book.md").write_text("shared with another computer")
    path = ws.config_dir / "storage.yaml"
    text = set_key(path.read_text(), ["backups", "targets"], [{"path": str(offsite), "label": ""}])
    text = set_key(text, ["backups", "automatic"], False)
    path.write_text(set_key(text, ["sync", "folder"], str(synced)))
    cfg = ws.config(env={})
    backup.run_backup(ws, cfg)
    backup.run_backup(ws, cfg)
    return ws, cfg, offsite, synced


def copy(folder: Path, name: str) -> Path:
    path = folder / name
    path.mkdir()
    (path / "thimbleby.db").write_bytes(b"x")
    return path


def test_the_plan_lists_the_database_the_history_the_export_and_only_this_workspaces_backups(env):
    ws, cfg, offsite, synced = env
    other = copy(offsite, "thimbleby-work-20260101-000000")
    left = copy(offsite, ".thimbleby-20260101-000000.part")
    found = erase.plan(ws, cfg)
    names = {(i.kind, i.name) for i in found.items}
    assert (erase.WORKSPACE, "thimbleby.db") in names and (erase.WORKSPACE, ".git") in names
    assert (erase.WORKSPACE, "data") in names and (erase.WORKSPACE, "config") in names
    assert sum(1 for i in found.items if i.kind == erase.BACKUP) == 2
    assert (erase.UNFINISHED, left.name) in names
    assert str(other) not in [i.path for i in found.items]
    history = next(i for i in found.items if i.name == ".git")
    assert history.commits and history.commits >= 1
    assert all(i.files >= 1 and i.bytes > 0 for i in found.items if i.name in ("thimbleby.db", "config"))
    assert [(i.kind, i.path) for i in found.stays] == [(erase.SYNCED, str(synced))]


def test_erasing_removes_the_workspace_its_history_and_its_backups_and_nothing_of_anyone_elses(env):
    ws, cfg, offsite, synced = env
    other = copy(offsite, "thimbleby-work-20260101-000000")
    left = copy(offsite, ".thimbleby-20260101-000000.part")
    found = erase.plan(ws, cfg)
    result = erase.erase(ws, cfg, found.token)
    assert result.failed == []
    assert not ws.root.exists()  # the folder, its database and its history
    assert other.is_dir() and offsite.is_dir() and not left.exists()
    assert [p.name for p in offsite.iterdir()] == [other.name]
    assert (synced / "book.md").is_file()  # shared with another computer: left, and the plan said so


def test_a_list_that_changed_since_the_person_looked_deletes_nothing(env):
    ws, cfg, offsite, _ = env
    found = erase.plan(ws, cfg)
    backup.run_backup(ws, cfg)  # a new copy appeared after the list was shown
    with pytest.raises(erase.EraseRefused, match="changed"):
        erase.erase(ws, cfg, found.token)
    with pytest.raises(erase.EraseRefused):
        erase.erase(ws, cfg, "not-the-token")
    assert ws.db_path.is_file() and len(list(offsite.iterdir())) == 3


def test_a_folder_that_is_not_a_workspaces_own_is_refused(env, tmp_path, monkeypatch):
    ws, cfg, *_ = env
    with pytest.raises(erase.EraseRefused):
        erase.plan(type(ws)(tmp_path), cfg)  # no config folder in it
    monkeypatch.setattr(Path, "home", lambda: ws.root)  # the home folder is never deleted, workspace or not
    with pytest.raises(erase.EraseRefused):
        erase.plan(ws, cfg)


def test_a_place_that_cannot_be_removed_is_reported_and_the_rest_still_goes(env, monkeypatch):
    ws, cfg, offsite, _ = env
    found = erase.plan(ws, cfg)
    stuck = next(i.path for i in found.items if i.kind == erase.BACKUP)
    real = erase._remove

    def remove(path):
        return "it is in use" if str(path) == stuck else real(path)

    monkeypatch.setattr(erase, "_remove", remove)
    result = erase.erase(ws, cfg, found.token)
    assert result.failed == [(stuck, "it is in use")]
    assert [p.name for p in offsite.iterdir()] == [Path(stuck).name]
    assert not ws.db_path.exists()


def test_the_command_lists_what_goes_and_deletes_only_with_the_workspaces_name(env, capsys):
    ws, cfg, offsite, _ = env
    assert main(["erase", "-w", str(ws.root)]) == 2  # not a terminal and no name given: nothing is deleted
    out = capsys.readouterr().out
    assert "thimbleby.db" in out and "a backup copy" in out and "Deleting one item in the app keeps its history" in out
    assert ws.db_path.is_file() and len(list(offsite.iterdir())) == 2
    assert main(["erase", "-w", str(ws.root), "--confirm", "someone-else"]) == 2
    assert ws.db_path.is_file()
    assert main(["erase", "-w", str(ws.root), "--confirm", NAME]) == 0
    assert not ws.root.exists() and list(offsite.iterdir()) == []


def test_the_command_refuses_while_the_app_is_running_on_the_workspace(env, capsys):
    from engine.storage.lease import Lease

    ws, *_ = env
    running = Store(ws.db_path)
    Lease(running, holder="the running app").acquire()
    try:
        assert main(["erase", "-w", str(ws.root), "--confirm", NAME]) == 1
        assert ws.db_path.is_file()
    finally:
        running.close()


# ---- the app's own route ----------

TOKEN = "erase-token"


@pytest.fixture
def api(env, tmp_path):
    from fastapi.testclient import TestClient

    from api.app import create_app

    ws, cfg, offsite, synced = env
    stopped: list[bool] = []
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", on_erased=lambda: stopped.append(True))
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.ws, client.offsite, client.synced, client.stopped = ws, offsite, synced, stopped
        yield client


def test_the_route_lists_what_goes_and_what_stays(api):
    found = api.get("/api/erase")
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["name"] == NAME and body["token"]
    kinds = [i["kind"] for i in body["items"]]
    assert kinds.count("backup") == 2 and "workspace" in kinds
    assert [i["kind"] for i in body["stays"]] == ["synced_folder"]
    assert {i["name"] for i in body["items"]} >= {"thimbleby.db", ".git", "data", "config"}


def test_the_route_deletes_only_the_list_it_was_given_and_then_the_app_stops(api):
    token = api.get("/api/erase").json()["token"]
    assert api.post("/api/erase", json={"token": "not-it"}).status_code == 409
    assert api.ws.db_path.is_file() and api.stopped == []
    done = api.post("/api/erase", json={"token": token})
    assert done.status_code == 200, done.text
    assert done.json()["failed"] == [] and done.json()["removed"] >= 3
    assert not api.ws.root.exists() and list(api.offsite.iterdir()) == []
    assert (api.synced / "book.md").is_file()
    assert api.stopped == [True]


def test_a_hosted_install_never_deletes_its_workspace_from_the_screen(env, tmp_path):
    from fastapi.testclient import TestClient

    ws, _cfg, *_ = env
    hosted = ws.config(env={}, flags={"server.mode": "hosted"})
    # the route itself refuses, whatever the deploy checks say about the rest of a hosted start
    from fastapi import FastAPI

    from api.erase_routes import build_erase_router

    app = FastAPI()
    app.include_router(build_erase_router(ws, hosted, None, None))
    client = TestClient(app)
    assert client.get("/api/erase").status_code == 403
    assert client.post("/api/erase", json={"token": "x"}).status_code == 403
    assert ws.db_path.is_file()
