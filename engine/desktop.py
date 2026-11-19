"""The start of the installed app: opening it, with nothing typed, starts the person's own workspace in the app-data
place, in the app's own window, behind a menu-bar or tray item.

The workspace is in the app-data folder (`engine/app_dirs.py`), made the first time with no template, unless the
environment names another (`THIMBLEBY_WORKSPACE`). A second open while the app runs brings its window forward. A
failure to start shows in the starting window as one message with Try again, never as raw text.
Everything goes through the same pieces `thimbleby serve` uses (`engine.cli.make_app`); this module adds the window, the
item, the one-instance lock and the folder."""

from __future__ import annotations

import contextlib
import os
import platform
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from engine.app_dirs import app_dirs
from engine.legacy_names import app_name, workspace_from_env

#: The folder inside the app's data folder that holds the workspace.
WORKSPACE_FOLDER = "workspace"
#: The file in the app's logs folder that says why the app could not start.
LOG_FILE = "desktop.log"
#: The add-ons bundled in the installed app that its first workspace starts with turned on (a workspace made any other
#: way keeps the setting `server.new_workspace_addons`, empty by default).
INSTALLED_APP_ADDONS: tuple[str, ...] = ()


def places(
    env: Mapping[str, str] | None = None, home: Path | None = None, system: str | None = None
) -> tuple[Path, Path]:
    """The workspace folder and the logs folder: the workspace the environment names, else one inside the app's data
    folder; the logs folder is the system's place for them."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    system = system or platform.system() or "Linux"
    dirs = app_dirs(system, env, home, app_name(system, env, home))
    chosen = workspace_from_env(env)
    return (Path(chosen).expanduser() if chosen else Path(dirs.data) / WORKSPACE_FOLDER), Path(dirs.logs)


def note_failure(logs: Path) -> None:
    """Write why the start failed where a person can find it: a windowed app has no terminal to say it in."""
    try:
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / LOG_FILE).open("a", encoding="utf-8") as out:
            out.write(traceback.format_exc() + "\n")
    except OSError:
        pass


def _first_workspace(root: Path, shell: Any) -> bool:
    """Make the app's own workspace. When the command-line version left one on this computer, ask once whether to
    use it:
    "Use it" brings in a copy and leaves the original as it was, "Start fresh" leaves it alone. False when the person
    quit instead of answering (nothing is made)."""
    import datetime

    from engine import earlier_workspace
    from engine.legacy_names import db_file
    from engine.workspace import init_workspace

    found = earlier_workspace.find(Path.home(), root)
    if found is not None and hasattr(shell, "ask_earlier"):
        used = datetime.datetime.fromtimestamp(db_file(found.path).stat().st_mtime)
        answer = shell.ask_earlier(
            _shown_path(found.path), found.sides, found.todos, found.people, f"{used:%b} {used.day}"
        )
        if answer is None:
            return False
        if answer:
            earlier_workspace.bring_in(found.path, root)
            return True
    init_workspace(root, addons=INSTALLED_APP_ADDONS)
    return True


def _shown_path(path: Path) -> str:
    """The folder as a person reads it: under their home folder it starts with ~."""
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def start(
    root: Path,
    shell: Any,
    *,
    launch: Callable[..., None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Make the workspace when it isn't there, then run the app on it in the shell's window until the person quits.

    A second open of the app, while the first runs, only asks the first to bring its window forward."""
    from engine import build_info, cli, launcher, update_flow
    from engine.handover import open_or_hold
    from engine.legacy_names import private_dir
    from engine.local_guards import local_address_problem
    from engine.sides import word
    from engine.workspace import WorkspaceError, resolve

    folder = private_dir(root)
    if launcher.is_running(folder):
        launcher.show_running(folder, resolve(root).install_token())
        return
    shell.show_starting()
    if not (root / "config").is_dir():
        if root.exists() and any(p for p in root.iterdir() if p.name != folder.name):
            raise WorkspaceError(f"{root} already holds other files, so a workspace can't be made there.")
        if not _first_workspace(root, shell):
            return
    ws = resolve(root)
    env = dict(environ) if environ is not None else None
    cfg = ws.config(env=env)
    if cfg.server.mode == "hosted":
        raise WorkspaceError("The installed app runs on this computer only; set server.mode to local.")
    if problem := local_address_problem(cfg.server):
        raise WorkspaceError(problem)
    cli.remember_workspace(ws.root)
    shell.words = {**shell.words, **{k: word(cfg, k) for k in shell.words if k.startswith("desktop.")}}
    # What the last update left: a failed one shows its screen (and puts the copy of the work back when it was needed);
    # trying again starts the update here, before the workspace is opened.
    if not update_flow.settle(ws, cfg, shell, environ=env):
        return
    prefix = "" if cfg.server.base_path == "/" else cfg.server.base_path
    waiting = threading.Event()  # set when the app asked to restart, so the menu's Restart is on
    asked = threading.Event()
    finished = threading.Event()  # set when the workspace was deleted, so there is nothing left to run

    def ask_restart() -> None:
        waiting.set()
        asked.set()

    updating_now = threading.Lock()

    def ask_update(version: str) -> None:
        """The person chose Update and restart: run the update's steps in the window on their own thread. When the
        hand-over has started the app ends; when it didn't finish, or the person chose to go on, the app comes back."""

        def work() -> None:
            if not updating_now.acquire(blocking=False):
                return
            try:
                if update_flow.install(ws, ws.config(env=env), shell, version, environ=env):
                    shell.quit()
                elif not shell.quit_event.is_set():
                    shell.show_app(f"http://127.0.0.1:{cfg.server.port}{prefix}/?token={ws.install_token()}")
            finally:
                updating_now.release()

        threading.Thread(target=work, name="update", daemon=True).start()

    def look_at_update() -> None:
        """The item's dot and its Update line follow what the last look at the release feed kept, looked at every half
        minute (a read of one small file)."""
        from engine import update_offer

        if time.monotonic() < next_look[0]:
            return
        next_look[0] = time.monotonic() + 30
        now = ws.config(env=env)
        keys = update_offer.trusted_keys(now.updates)
        found = update_offer.offer(ws.private_dir, None, keys) if now.updates.check else None
        shell.set_update(found.version if found is not None else None)

    next_look = [0.0]
    shell.on("install", lambda: shell.update_offered and ask_update(shell.update_offered))

    def build() -> Any:
        """A new app on the workspace, each time the server starts, with a new sign-in token for it."""
        fresh = ws.config(env=env)
        opened = open_or_hold(ws, fresh)
        token = ws.new_install_token()
        app, _ = cli.make_app(
            ws, fresh, token, opened, on_restart=ask_restart, on_erased=finished.set, on_update=ask_update
        )
        return app

    shell.step(1)
    (launch or launcher.launch)(
        build,
        cfg.server.port,
        ws.private_dir,
        shell=shell,
        open_path=lambda: f"{prefix}/?token={ws.install_token()}",
        readiness_path=f"{prefix}/api/health",
        restart_waiting=waiting.is_set,
        restarted=waiting.clear,
        restart_requested=asked,
        quit_requested=finished,
        token=ws.install_token,
        ready=lambda: update_flow.started(ws),
        poll=look_at_update,
        identity=build_info.current().identity(),
    )


def run(
    root: Path,
    logs: Path,
    shell: Any,
    *,
    environ: Mapping[str, str] | None = None,
    launch: Callable[..., None] | None = None,
) -> int:
    """Start the app, and while it can't start, show why in the window and start again each time the person says to."""
    from engine.startpage import classify

    while True:
        try:
            start(root, shell, environ=environ, launch=launch)
            return 0
        except BaseException as err:
            if isinstance(err, SystemExit | KeyboardInterrupt):
                raise
            note_failure(logs)
            if not shell.problem(classify(err), traceback.format_exc()):
                return 1


#: What a second open found: no other copy ("none", this one goes on), the running copy shown ("shown"), or an older
#: copy that was asked to finish and didn't ("stuck", the person is told how to quit it).
NONE, SHOWN, STUCK = "none", "shown", "stuck"


def already_running(root: Path, environ: Mapping[str, str] | None = None) -> str:
    """A second open of the app: when another copy runs on this workspace, before this copy makes any window of its own
    (a window, even hidden, would keep this copy running):

    - a copy that is newer than the running one asks it to finish, and goes on to serve once it has (`NONE`), or is
      `STUCK` when the older one doesn't finish in `updates.takeover_wait_seconds`;
    - the same or an older copy asks the running one to bring its window forward (`SHOWN`)."""
    from engine import build_info, launcher
    from engine.legacy_names import private_dir
    from engine.workspace import resolve

    folder = private_dir(root)
    if not launcher.is_running(folder):
        launcher.note(f"no copy holds {folder}; starting")
        return NONE
    ws = resolve(root)
    token = ws.install_token()
    lock = launcher.InstanceLock(folder)
    running = build_info.from_published(lock.identity())
    mine = build_info.current()
    if lock.control_port() is not None and build_info.is_newer(mine, running):
        launcher.note(f"another copy holds {folder} and is older ({running}); asking it to finish")
        wait = ws.config(env=dict(environ) if environ is not None else None).updates.takeover_wait_seconds
        return NONE if launcher.stop_running(folder, token, wait=wait) else STUCK
    launcher.note(f"another copy holds {folder}")
    launcher.show_running(folder, token)
    return SHOWN


def main(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    argv: list[str] | None = None,
    make_shell: Callable[..., Any] | None = None,
) -> int:
    """The frozen app's entry with no arguments (or with `--at-login`). Returns the exit code; a failure is shown in the
    window and written to the logs folder."""
    from engine import __version__, login_item
    from engine.appwindow_backends import make_shell as real_shell
    from engine.sides import words_sheet

    root, logs = places(environ, home)
    from engine import launcher

    launcher.NOTE_FILE = logs / LOG_FILE
    found = already_running(root, environ)
    if found == SHOWN:
        return 0
    system = platform.system()
    words = {k: str(v) for k, v in words_sheet().items() if k.startswith("desktop.")}
    quiet = login_item.AT_LOGIN_FLAG in (sys.argv[1:] if argv is None else argv)
    shell = (make_shell or real_shell)(
        words,
        version=__version__,
        storage=logs.parent / "webview",
        login_on=lambda: login_item.is_enabled(system),
        quiet=quiet,
    )

    def toggle_login() -> None:
        login_item.toggle(system)
        shell.set_state(shell.state)  # the item shows the new choice

    def check_for_update() -> None:
        """The menu's Check for a new version: look at the release feed now; a newer version brings the window forward
        to Today, where it is offered. A look that can't be made says nothing."""
        from engine import update_offer
        from engine.workspace import resolve as workspace

        with contextlib.suppress(Exception):
            ws = workspace(root)
            if update_offer.check_now(ws, ws.config(env=dict(environ) if environ is not None else None)) is not None:
                shell.bring_forward()

    shell.on("login", toggle_login)
    shell.on("update", check_for_update)

    def go() -> int:
        # An older copy that wouldn't finish: say how to quit it, and look again each time the person says to.
        while found == STUCK:
            if not shell.problem("older_running", ""):
                return 1
            if (found_now := already_running(root, environ)) == SHOWN:
                return 0
            if found_now == NONE:
                break
        return run(root, logs, shell, environ=environ)

    return shell.run(go)
