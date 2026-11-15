"""The start of the installed app: opening it, with nothing typed, starts the person's own workspace in the app-data
place, in the app's own window, behind a menu-bar or tray item.

The workspace is in the app-data folder (`engine/app_dirs.py`), made the first time with no template, unless the
environment names another (`THIMBLEBY_WORKSPACE`). A second open while the app runs brings its window forward. A
failure to start shows in the starting window as one message with Try again, never as raw text.
Everything goes through the same pieces `thimbleby serve` uses (`engine.cli.make_app`); this module adds the window, the
item, the one-instance lock and the folder."""

from __future__ import annotations

import os
import platform
import sys
import threading
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


def start(
    root: Path,
    shell: Any,
    *,
    launch: Callable[..., None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Make the workspace when it isn't there, then run the app on it in the shell's window until the person quits.

    A second open of the app, while the first runs, only asks the first to bring its window forward."""
    from engine import cli, launcher
    from engine.handover import open_or_hold
    from engine.legacy_names import private_dir
    from engine.local_guards import local_address_problem
    from engine.sides import word
    from engine.workspace import WorkspaceError, init_workspace, resolve

    folder = private_dir(root)
    if launcher.is_running(folder):
        launcher.show_running(folder, resolve(root).install_token())
        return
    shell.show_starting()
    if not (root / "config").is_dir():
        if root.exists() and any(p for p in root.iterdir() if p.name != folder.name):
            raise WorkspaceError(f"{root} already holds other files, so a workspace can't be made there.")
        init_workspace(root)
    ws = resolve(root)
    env = dict(environ) if environ is not None else None
    cfg = ws.config(env=env)
    if cfg.server.mode == "hosted":
        raise WorkspaceError("The installed app runs on this computer only; set server.mode to local.")
    if problem := local_address_problem(cfg.server):
        raise WorkspaceError(problem)
    cli.remember_workspace(ws.root)
    shell.words = {**shell.words, **{k: word(cfg, k) for k in shell.words if k.startswith("desktop.")}}
    prefix = "" if cfg.server.base_path == "/" else cfg.server.base_path
    waiting = threading.Event()  # set when the app asked to restart, so the menu's Restart is on
    asked = threading.Event()
    finished = threading.Event()  # set when the workspace was deleted, so there is nothing left to run

    def ask_restart() -> None:
        waiting.set()
        asked.set()

    def build() -> Any:
        """A new app on the workspace, each time the server starts, with a new sign-in token for it."""
        fresh = ws.config(env=env)
        opened = open_or_hold(ws, fresh)
        token = ws.new_install_token()
        app, _ = cli.make_app(ws, fresh, token, opened, on_restart=ask_restart, on_erased=finished.set)
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

    shell.on("login", toggle_login)
    return shell.run(lambda: run(root, logs, shell, environ=environ))
