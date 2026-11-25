"""The installed app's start with nothing typed (TB2): the workspace is made in the app-data place, the tray loop is
given the base path, the sign-in link and the health address, and a failure is written where a person can find it."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from engine import desktop
from engine.workspace import resolve
from tests.test_restore_in_app import (
    made as backed_up,  # noqa: F401  (a workspace with one backup copy and later changes)
)


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

    def on(self, key, action):
        pass

    def set_update(self, version):
        pass

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
    import socket

    with socket.socket() as pick:  # a free port the test chose, never an assumed one
        pick.bind(("127.0.0.1", 0))
        free = pick.getsockname()[1]
    env = env_for(tmp_path, THIMBLEBY__SERVER__BASE_PATH="/thimble", THIMBLEBY__SERVER__PORT=str(free))

    def launch(factory, port, folder, **options):
        given.update(options, port=port, folder=folder)
        with TestClient(factory()) as client:
            given["health"] = client.get(options["readiness_path"]).status_code
        # The sign-in link is the one the running app was started with.
        given["path"] = options["open_path"]()

    desktop.start(root, shell, launch=launch, environ=env)
    ws = resolve(root)
    assert (root / "config").is_dir() and ws.db_path.exists()
    # The installed app bundles no add-on: its first workspace starts with none on.
    assert ws.config().workspace.plugins.enabled == []
    assert not (root / "data" / "plugins").exists() and "demo" not in {p.name for p in root.iterdir()}
    assert given["port"] == free and given["folder"] == ws.private_dir
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
    assert made["quiet"] is True and made["keys"] == ["login", "update"]
    assert made["words"]["desktop.title"] == "Thimbleby"
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


# ---- a newly installed build takes over from an older copy still running (S-0662) ------------------------------------


def _running_copy(root, tmp_path, monkeypatch, *, identity, finishes):
    """A copy running on the workspace, as another process would be: it holds the lock, publishes its address and
    identity, and listens for the quit request (which lets go of the folder only when `finishes`)."""
    import engine.launcher as launcher
    from engine.legacy_names import private_dir

    desktop.start(root, Shell(), launch=lambda *a, **k: None, environ=env_for(tmp_path))  # makes the workspace
    lock = launcher.InstanceLock(private_dir(root))
    assert lock.acquire()
    quit_asked = []

    def on_quit():
        quit_asked.append(True)
        if finishes:
            lock.release()

    control = launcher.ControlServer(resolve(root).install_token, lambda: quit_asked.append("show"), on_quit)
    lock.publish(8123, "/api/health", control.start(), identity)
    shown = []
    monkeypatch.setattr(launcher, "show_running", lambda folder, token: shown.append(token))
    return lock, control, quit_asked, shown


def _this_build(monkeypatch, version="0.1.0", number=52):
    from engine import build_info

    monkeypatch.setattr(build_info, "current", lambda catalog=None: build_info.Build(version, number, "abc1234"))


def test_a_newer_build_asks_an_older_running_copy_to_finish_and_then_serves(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    older = {"version": "0.1.0", "build": 51, "commit": "def5678"}
    lock, control, quit_asked, shown = _running_copy(root, tmp_path, monkeypatch, identity=older, finishes=True)
    try:
        _this_build(monkeypatch, number=52)
        assert desktop.already_running(root, env_for(tmp_path)) == desktop.NONE
        assert quit_asked == [True] and shown == []
    finally:
        control.stop()
        lock.release()


def test_a_copy_that_published_no_identity_is_older_than_any_stamped_build(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    lock, control, quit_asked, shown = _running_copy(root, tmp_path, monkeypatch, identity=None, finishes=True)
    try:
        _this_build(monkeypatch, number=52)
        assert desktop.already_running(root, env_for(tmp_path)) == desktop.NONE and quit_asked == [True]
    finally:
        control.stop()
        lock.release()


@pytest.mark.parametrize("running_number", [52, 53])
def test_the_same_or_an_older_build_shows_the_running_copy_and_asks_it_nothing_else(
    tmp_path, monkeypatch, running_number
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    running = {"version": "0.1.0", "build": running_number, "commit": "def5678"}
    lock, control, quit_asked, shown = _running_copy(root, tmp_path, monkeypatch, identity=running, finishes=True)
    try:
        _this_build(monkeypatch, number=52)
        assert desktop.already_running(root, env_for(tmp_path)) == desktop.SHOWN
        assert quit_asked == [] and shown == [resolve(root).install_token()]
    finally:
        control.stop()
        lock.release()


def test_an_older_copy_that_does_not_finish_in_its_time_is_stuck_and_the_window_says_how_to_quit_it(
    tmp_path, monkeypatch
):
    import engine.launcher as launcher

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Where the app itself looks on this system (on a Mac, Application Support; elsewhere the data folder), so the
    # copy the test starts is the one the window's own second look finds.
    root, _ = desktop.places(env_for(tmp_path), tmp_path / "home")
    older = {"version": "0.1.0", "build": 51, "commit": "def5678"}
    lock, control, quit_asked, shown = _running_copy(root, tmp_path, monkeypatch, identity=older, finishes=False)
    try:
        _this_build(monkeypatch, number=52)
        waited = []
        real = launcher.stop_running
        monkeypatch.setattr(
            launcher,
            "stop_running",
            lambda folder, token, wait: (
                waited.append(wait)
                or real(folder, token, wait=wait, clock=iter([0, 1, 2, 99, 100, 101]).__next__, pause=lambda s: None)
            ),
        )
        assert desktop.already_running(root, env_for(tmp_path)) == desktop.STUCK
        assert quit_asked == [True] and waited == [20]  # updates.takeover_wait_seconds

        shell = Shell()
        made = {}

        class Entry(Shell):
            def __init__(self, words, **options):
                super().__init__(words)
                shell.words = self.words

            def run(self, work):
                made["code"] = work()
                return made["code"]

            def problem(self, kind, details):
                shell.problems.append((kind, details))
                return False

        assert desktop.main(env_for(tmp_path), tmp_path / "home", argv=[], make_shell=Entry) == 1
        assert [kind for kind, _ in shell.problems] == ["older_running"]
        from engine import startpage

        title, text = startpage.message(shell.words, "older_running")
        assert "older" in title.lower() and "Quit" in text and shown == []
    finally:
        control.stop()
        lock.release()


def test_a_running_copy_of_the_same_build_is_never_asked_to_quit_by_a_source_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    running = {"version": "0.1.0", "build": 51, "commit": "def5678"}
    lock, control, quit_asked, shown = _running_copy(root, tmp_path, monkeypatch, identity=running, finishes=True)
    try:
        from engine import build_info

        monkeypatch.setattr(build_info, "current", lambda catalog=None: build_info.Build("0.1.0"))
        assert desktop.already_running(root, env_for(tmp_path)) == desktop.SHOWN and quit_asked == []
    finally:
        control.stop()
        lock.release()


@pytest.mark.parametrize("system", ["Darwin", "Windows", "Linux"])
def test_the_saved_keys_are_inside_the_app_data_folder_on_each_system(system):
    from engine.app_dirs import app_dirs
    from engine.legacy_names import private_dir

    home = {"Darwin": "/Users/rowan", "Windows": r"C:\Users\Rowan", "Linux": "/home/rowan"}[system]
    root, _ = desktop.places({}, home, system)
    data = Path(app_dirs(system, {}, home, desktop.app_name(system, {}, home)).data)
    keys = private_dir(root) / "keys"
    assert str(keys).startswith(str(data))
    assert "Roaming" not in str(keys)


# ---- a restore the person staged, from the installed app's own start (S-0791) ----------------------------------------


def test_the_installed_apps_start_and_each_restart_swap_a_staged_restore_in_before_opening_the_workspace(
    backed_up,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    from engine import restore_in_app
    from tests.test_restore_in_app import add_person, counts

    ws, _, copy, at_copy = backed_up
    assert counts(ws.db_path) != at_copy
    restore_in_app.stage(ws, copy)
    seen = {}

    def launch(factory, port, folder, **options):
        # Quit and open: the first start builds the app on the copy's data.
        with TestClient(factory()):
            seen["first"] = counts(ws.db_path)[0]["person"]
        assert not (ws.private_dir / restore_in_app.PENDING).exists()
        # The person chooses Restart now after staging another restore: the same build function swaps it in.
        add_person(ws, "Added Again")
        restore_in_app.stage(ws, copy)
        with TestClient(factory()):
            seen["restart"] = counts(ws.db_path)[0]["person"]

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    desktop.start(ws.root, Shell(), launch=launch, environ=env_for(tmp_path))
    people = at_copy[0]["person"]  # what was added after the copy is gone, both times
    assert seen == {"first": people, "restart": people}
    assert restore_in_app.note(ws).state == restore_in_app.RESTORED


def test_the_launchers_restart_builds_the_app_again_so_restart_now_reaches_the_swap(tmp_path, monkeypatch):
    import threading

    from engine import launcher

    builds = []

    class Window:
        quit_event = threading.Event()
        restart_enabled = None

        def __getattr__(self, name):
            return lambda *a, **k: None

        def on(self, key, action):
            if key == "restart":
                self.restart = action

        def show_app(self, url):
            # The window is up: the person chose Restart now, then quit.
            self.restart()
            self.quit_event.set()

    class Quiet:
        def __init__(self, app):
            pass

    monkeypatch.setattr(launcher, "wait_ready", lambda *a, **k: True)
    monkeypatch.setattr(launcher.LocalServer, "start", lambda self: setattr(self, "thread", None))
    monkeypatch.setattr(launcher.LocalServer, "stop", lambda self: None)
    monkeypatch.setattr(launcher.LocalServer, "alive", lambda self: True)
    swapped = []
    monkeypatch.setattr(launcher.LocalServer, "swap", lambda self, timeout=60: swapped.append(self.app_factory()))
    waiting = threading.Event()
    waiting.set()
    launcher.launch(
        lambda: builds.append("build") or "app",
        0 + 51234,
        tmp_path,
        shell=Window(),
        open_path="/",
        restart_waiting=waiting.is_set,
    )
    assert builds == ["build"] and swapped == ["app"]  # the restart builds the app again, which is where the swap is


# ---- the port (S-0792) ---------------------------------------------------------------------------------


def test_a_taken_port_moves_the_app_to_the_next_free_one_and_every_setting_follows_it(tmp_path, monkeypatch):
    import socket

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    taken = holder.getsockname()[1]
    env = env_for(tmp_path, THIMBLEBY__SERVER__PORT=str(taken), THIMBLEBY__SERVER__BASE_PATH="/thimble")
    given = {}

    def launch(factory, port, folder, **options):
        given["port"] = port
        given["path"] = options["open_path"]()
        with TestClient(factory(), base_url=f"http://127.0.0.1:{port}") as client:
            given["health"] = client.get(options["readiness_path"]).status_code

    try:
        desktop.start(root, Shell(), launch=launch, environ=env)
    finally:
        holder.close()
    assert given["port"] != taken and taken < given["port"] <= taken + 20
    assert given["health"] == 200 and given["path"].startswith("/thimble/?token=")


def test_with_no_port_free_the_window_names_the_range_and_stays_until_the_person_chooses(tmp_path, monkeypatch):
    from engine import launcher

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "share" / "thimbleby" / desktop.WORKSPACE_FOLDER
    monkeypatch.setattr(launcher, "port_is_free", lambda port: False)
    monkeypatch.setattr(launcher.choose_port, "__defaults__", (lambda port: False,))
    shell = Shell()
    env = env_for(tmp_path, THIMBLEBY__SERVER__PORT="9000", THIMBLEBY__SERVER__PORT_TRIES="3")
    assert desktop.run(root, tmp_path / "logs", shell, environ=env, launch=lambda *a, **k: None) == 1
    ((kind, _),) = shell.problems
    text = shell.words["desktop.problem.ports.text"]
    assert kind == "ports" and "9000 to 9003" in text
    assert "computer usually fixes" not in text and "Restarting the computer" not in text


def test_choosing_a_port_skips_held_ones_and_stops_at_the_limit():
    from engine import launcher

    assert launcher.choose_port(100, 5, free=lambda p: p >= 102) == 102
    with pytest.raises(launcher.PortsTaken) as err:
        launcher.choose_port(100, 2, free=lambda p: False)
    assert (err.value.first, err.value.last) == (100, 102)
    assert launcher.choose_port(65535, 10, free=lambda p: True) == 65535
