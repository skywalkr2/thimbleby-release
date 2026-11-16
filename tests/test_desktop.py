"""The installed app's start with nothing typed (TB2): the workspace is made in the app-data place, the tray loop is
given the base path, the sign-in link and the health address, and a failure is written where a person can find it."""

from pathlib import Path

from starlette.testclient import TestClient

from engine import desktop
from engine.workspace import resolve


class Shell:
    """What the start talks to: it records the steps and the window's first show, and holds the words."""

    def __init__(self, words=None):
        self.words = dict(words if words is not None else desktop_words())
        self.calls = []
        self.problems = []
        self.retry = False
        self.asked = []
        self.answer = False

    def show_starting(self):
        self.calls.append("starting")

    def step(self, done):
        self.calls.append(("step", done))

    def ask_earlier(self, path, sides, todos, people, used):
        self.asked.append((path, sides, todos, people))
        return self.answer

    def problem(self, kind, details):
        self.problems.append((kind, details))
        return self.retry


def desktop_words():
    from engine.sides import words_sheet

    return {k: str(v) for k, v in words_sheet().items() if k.startswith("desktop.")}


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


def test_the_first_start_makes_the_workspace_with_no_template_and_runs_the_window_on_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    given = {}
    shell = Shell()
    env = env_for(tmp_path, THIMBLEBY__SERVER__BASE_PATH="/thimble")

    def launch(factory, port, folder, **options):
        given.update(options, port=port, folder=folder)
        with TestClient(factory()) as client:
            given["health"] = client.get(options["readiness_path"]).status_code
        # The sign-in link is the one the running app was started with.
        given["path"] = options["open_path"]()

    desktop.start(root, shell, launch=launch, environ=env)
    ws = resolve(root)
    assert (root / "config").is_dir() and ws.db_path.exists()
    # The installed app's first workspace starts with the bundled parcels add-on on, with no Add-ons screen.
    assert ws.config().workspace.plugins.enabled == ["parcels"]
    assert not (root / "data" / "plugins").exists() and "demo" not in {p.name for p in root.iterdir()}
    assert given["port"] == ws.config().server.port and given["folder"] == ws.private_dir
    assert given["readiness_path"] == "/thimble/api/health" and given["health"] == 200
    assert given["path"] == f"/thimble/?token={ws.install_token()}"
    assert given["shell"] is shell and given["token"]() == ws.install_token()
    # The window is up before the workspace is made, and the first step is ticked once it is.
    assert shell.calls == ["starting", ("step", 1)]


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

    desktop.start(root, Shell(), launch=launch, environ=env_for(tmp_path))
    assert seen == {"waiting": True, "asked": True, "after": False, "quit": True}


def test_a_folder_holding_other_files_is_not_made_over_and_the_reason_is_logged_and_shown_plainly(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    root.mkdir(parents=True)
    (root / "mine.txt").write_text("keep")
    logs = tmp_path / "state" / "thimbleby" / "logs"
    shell = Shell()
    assert desktop.run(root, logs, shell, environ=env_for(tmp_path)) == 1
    assert (root / "mine.txt").read_text() == "keep"
    assert "already holds other files" in (logs / desktop.LOG_FILE).read_text()
    assert [kind for kind, _ in shell.problems] == ["other"]


def test_try_again_starts_again_and_a_full_disk_is_named(tmp_path, monkeypatch):
    import errno

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    attempts = []

    def launch(factory, port, folder, **options):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError(errno.ENOSPC, "No space left on device")

    shell = Shell()
    shell.retry = True
    assert desktop.run(root, tmp_path / "logs", shell, environ=env_for(tmp_path), launch=launch) == 0
    assert [kind for kind, _ in shell.problems] == ["disk_full"] and len(attempts) == 2


def test_a_second_open_shows_no_starting_window_and_asks_the_running_app_to_show_its_own(tmp_path, monkeypatch):
    import engine.launcher as launcher

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    desktop.start(root, Shell(), launch=lambda *a, **k: None, environ=env_for(tmp_path))  # makes the workspace
    asked = []
    monkeypatch.setattr(launcher, "is_running", lambda folder: True)
    monkeypatch.setattr(launcher, "show_running", lambda folder, token: asked.append(token))
    shell = Shell()
    desktop.start(root, shell, launch=lambda *a, **k: asked.append("started"), environ=env_for(tmp_path))
    assert asked == [resolve(root).install_token()] and shell.calls == []


def test_a_second_open_makes_no_window_at_all_so_it_exits_once_the_first_shows_its_own(tmp_path, monkeypatch):
    """A window, even a hidden one, keeps its copy of the app running: a second open that made one never ended."""
    import engine.launcher as launcher

    home = tmp_path / "home"
    root, _ = desktop.places(env_for(tmp_path), home)
    desktop.start(root, Shell(), launch=lambda *a, **k: None, environ=env_for(tmp_path))  # makes the workspace
    asked = []
    monkeypatch.setattr(launcher, "is_running", lambda folder: True)
    monkeypatch.setattr(launcher, "show_running", lambda folder, token: asked.append(token))

    def no_window(*a, **k):
        raise AssertionError("a second open made a window")

    assert desktop.main(env_for(tmp_path), home, argv=[], make_shell=no_window) == 0
    assert asked == [resolve(root).install_token()]


def test_the_entry_opens_quietly_at_login_and_runs_the_start_in_the_shell(tmp_path):
    made = {}

    class Entry:
        def __init__(self, words, **options):
            made.update(options, words=words)

        def on(self, key, action):
            made.setdefault("keys", []).append(key)

        def run(self, work):
            made["worked"] = True
            return 7

    assert desktop.main(env_for(tmp_path), tmp_path / "home", argv=["--at-login"], make_shell=Entry) == 7
    assert made["quiet"] is True and made["keys"] == ["login"] and made["words"]["desktop.title"] == "Thimbleby"
    made.clear()
    desktop.main(env_for(tmp_path), tmp_path / "home", argv=[], make_shell=Entry)
    assert made["quiet"] is False


def earlier_workspace_of(tmp_path, monkeypatch):
    """A workspace made by the command-line version in the person's home folder, with one person in it."""
    from engine.folder_names import DEFAULT_FOLDER
    from engine.workspace import init_workspace

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    earlier = init_workspace(tmp_path / "home" / DEFAULT_FOLDER, git=False, you="Example Person")
    (earlier.root / "notes.txt").write_text("my own file", encoding="utf-8")
    return earlier.root


def snapshot(folder):
    return {
        p.relative_to(folder): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and ".thimbleby" not in p.parts and not p.name.endswith(("-shm", "-wal"))
    }


def run_start(root, shell, tmp_path):
    started = []
    desktop.start(root, shell, launch=lambda *a, **k: started.append(1), environ=env_for(tmp_path))
    return started


def test_the_first_run_asks_about_earlier_work_and_use_it_brings_in_a_copy_and_leaves_the_original(
    tmp_path, monkeypatch
):
    earlier = earlier_workspace_of(tmp_path, monkeypatch)
    before = snapshot(earlier)
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    shell = Shell()
    shell.answer = True
    assert run_start(root, shell, tmp_path) == [1]
    path, sides, todos, people = shell.asked[0]
    assert path.endswith(earlier.name) and path.startswith("~/") and people == 1 and sides >= 1 and todos == 0
    assert (root / "notes.txt").read_text(encoding="utf-8") == "my own file"
    assert resolve(root).db_path.is_file()
    assert snapshot(earlier) == before  # the original is as it was
    # Asked once: the workspace is there now, so the next start asks nothing.
    shell.asked.clear()
    run_start(root, shell, tmp_path)
    assert shell.asked == []


def test_start_fresh_makes_a_new_workspace_and_touches_nothing_of_the_earlier_one(tmp_path, monkeypatch):
    earlier = earlier_workspace_of(tmp_path, monkeypatch)
    before = snapshot(earlier)
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    shell = Shell()
    assert run_start(root, shell, tmp_path) == [1] and len(shell.asked) == 1
    assert not (root / "notes.txt").exists() and resolve(root).db_path.is_file()
    assert snapshot(earlier) == before
    shell.asked.clear()
    run_start(root, shell, tmp_path)
    assert shell.asked == []


def test_quitting_the_question_makes_nothing(tmp_path, monkeypatch):
    earlier_workspace_of(tmp_path, monkeypatch)
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    shell = Shell()
    shell.answer = None
    assert run_start(root, shell, tmp_path) == []
    assert not root.exists()


def test_with_no_earlier_work_nothing_is_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    shell = Shell()
    run_start(root, shell, tmp_path)
    assert shell.asked == []
