"""The installed app's start with nothing typed (TB2): the workspace is made in the app-data place, the tray loop is
given the base path, the sign-in link and the health address, and a failure is written where a person can find it."""

from pathlib import Path

from starlette.testclient import TestClient

from engine import desktop
from engine.workspace import resolve


def env_for(tmp_path: Path, **more: str) -> dict[str, str]:
    return {"XDG_DATA_HOME": str(tmp_path / "share"), "XDG_STATE_HOME": str(tmp_path / "state"), **more}


def test_the_workspace_is_in_the_app_data_place_unless_the_environment_names_one(tmp_path):
    home = tmp_path / "home"
    root, logs = desktop.places(env_for(tmp_path), home, "Linux")
    assert root == tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    assert logs == tmp_path / "state" / "thimbleby" / "logs"
    named = tmp_path / "named"
    root, _ = desktop.places(env_for(tmp_path, THIMBLEBY_WORKSPACE=str(named)), home, "Linux")
    assert root == named


def test_a_computer_with_the_data_folder_of_the_earlier_name_keeps_using_it(tmp_path):
    (tmp_path / "share" / "cockpit").mkdir(parents=True)
    root, _ = desktop.places(env_for(tmp_path), tmp_path / "home", "Linux")
    assert root == tmp_path / "share" / "cockpit" / desktop.WORKSPACE_FOLDER
    (tmp_path / "share" / "thimbleby").mkdir()
    root, _ = desktop.places(env_for(tmp_path), tmp_path / "home", "Linux")
    assert root == tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER


def test_the_first_start_makes_the_workspace_with_no_template_and_runs_the_tray_on_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    given = {}
    env = env_for(tmp_path, THIMBLEBY__SERVER__BASE_PATH="/thimble")

    def launch(factory, port, folder, **options):
        given.update(options, port=port, folder=folder)
        with TestClient(factory()) as client:
            given["health"] = client.get(options["readiness_path"]).status_code
        # The sign-in link is the one the running app was started with.
        given["path"] = options["open_path"]()

    desktop.start(root, launch=launch, environ=env)
    ws = resolve(root)
    assert (root / "config").is_dir() and ws.db_path.exists()
    assert not (root / "data" / "plugins").exists() and "demo" not in {p.name for p in root.iterdir()}
    assert given["port"] == ws.config().server.port and given["folder"] == ws.private_dir
    assert given["readiness_path"] == "/thimble/api/health" and given["health"] == 200
    assert given["path"] == f"/thimble/?token={ws.install_token()}"
    assert given["labels"] == {"open": "Open Thimbleby", "restart": "Restart", "quit": "Quit"}
    assert given["title"] == "Thimbleby"


def test_the_app_asking_for_a_restart_turns_the_menus_restart_on_and_asks_for_it(tmp_path, monkeypatch):
    import engine.cli as cli

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    callbacks = {}
    real = cli.make_app

    def recording(*args, **kwargs):
        callbacks.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "make_app", recording)
    seen = {}

    def launch(factory, port, folder, **options):
        assert not options["restart_waiting"]() and not options["restart_requested"].is_set()
        with TestClient(factory()):
            callbacks["on_restart"]()
        seen["waiting"] = options["restart_waiting"]()
        seen["asked"] = options["restart_requested"].is_set()
        options["restarted"]()
        seen["after"] = options["restart_waiting"]()
        callbacks["on_erased"]()
        seen["quit"] = options["quit_requested"].is_set()

    desktop.start(root, launch=launch, environ=env_for(tmp_path))
    assert seen == {"waiting": True, "asked": True, "after": False, "quit": True}


def test_a_folder_holding_other_files_is_not_made_over_and_the_reason_is_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    root.mkdir(parents=True)
    (root / "mine.txt").write_text("keep")
    assert desktop.main(env_for(tmp_path), tmp_path / "home") == 1
    assert (root / "mine.txt").read_text() == "keep"
    assert "already holds other files" in (tmp_path / "state" / "thimbleby" / "logs" / desktop.LOG_FILE).read_text()
