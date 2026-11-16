"""Removing the installed app from a Mac (Settings, Advanced): the card shows only for the installed Mac app, "Open the
folder" shows the work's folder, and "Quit and show the app" shows the app in Finder and then quits it by the
menu's path. Nothing is deleted."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.desktop_routes import build_desktop_router
from engine import app_removal
from engine.workspace import init_workspace

EXE = "/Applications/Thimbleby.app/Contents/MacOS/Thimbleby"


def planned(system="Darwin", exe=EXE, frozen=True, tmp_path=Path("/home/me")):
    return app_removal.plan(system, exe, frozen, {}, tmp_path)


def test_the_card_is_for_the_installed_mac_app_only():
    mac = planned()
    assert mac.available and mac.app == Path("/Applications/Thimbleby.app")
    assert mac.folder == Path("/home/me/Library/Application Support/thimbleby")
    assert not planned(frozen=False).available  # run from source
    assert not planned(system="Windows").available and not planned(system="Linux").available
    assert not planned(exe="/usr/bin/python3").available  # not inside an app folder


def test_the_folder_is_only_opened_and_the_app_only_shown_never_removed(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    removal = app_removal.Removal(True, Path("/Applications/Thimbleby.app"), folder)
    ran = []
    assert app_removal.open_folder(removal, ran.append) and app_removal.show_app(removal, ran.append)
    assert ran == [["open", str(folder)], ["open", "-R", "/Applications/Thimbleby.app"]]
    # A folder that is not there yet, or another system, runs nothing.
    assert not app_removal.open_folder(app_removal.Removal(True, None, tmp_path / "none"), ran.append)
    assert not app_removal.open_folder(app_removal.Removal(False, None, None), ran.append)
    assert not app_removal.show_app(app_removal.Removal(False, None, None), ran.append)
    assert len(ran) == 2


@pytest.fixture
def client(tmp_path, monkeypatch):
    ws = init_workspace(tmp_path / "ws", git=False)
    folder = tmp_path / "data"
    folder.mkdir()
    ran, quit_asked = [], []
    monkeypatch.setattr(app_removal, "_run", lambda command: ran.append(command))
    monkeypatch.setattr("api.desktop_routes.ask_to_show", lambda port, token, what: quit_asked.append((port, what)))
    monkeypatch.setattr(
        "api.desktop_routes.InstanceLock", lambda folder: type("L", (), {"control_port": lambda s: 4321})()
    )
    shown = {"on": True}

    def build(mode="local"):
        cfg = ws.config(env={}, flags={"server.mode": mode})
        found = app_removal.Removal(shown["on"], Path("/Applications/Thimbleby.app"), folder)
        app = FastAPI()
        app.include_router(build_desktop_router(ws, cfg, lambda: found))
        return TestClient(app)

    build.ran, build.quit_asked, build.shown, build.folder = ran, quit_asked, shown, folder
    return build


def test_the_card_names_the_folder_and_the_buttons_act(client):
    api = client()
    view = api.get("/api/desktop/removal").json()
    assert view == {"available": True, "folder": str(client.folder)}
    assert api.post("/api/desktop/removal/open-folder").status_code == 204
    assert api.post("/api/desktop/removal/show-app").status_code == 204
    # The app is shown in Finder first, then asked to quit by the menu's own path once the answer is sent.
    assert client.ran == [["open", str(client.folder)], ["open", "-R", "/Applications/Thimbleby.app"]]
    assert client.quit_asked == [(4321, "quit")]


def test_where_it_is_not_the_installed_mac_app_the_card_is_off_and_the_actions_are_refused(client):
    client.shown["on"] = False
    api = client()
    assert api.get("/api/desktop/removal").json() == {"available": False, "folder": ""}
    assert api.post("/api/desktop/removal/open-folder").status_code == 403
    assert api.post("/api/desktop/removal/show-app").status_code == 403
    client.shown["on"] = True
    refused = client("hosted")
    assert refused.get("/api/desktop/removal").json()["available"] is False
    assert refused.post("/api/desktop/removal/show-app").status_code == 403
    assert client.ran == [] and client.quit_asked == []
