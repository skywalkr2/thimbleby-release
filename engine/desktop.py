"""The start of the installed app: opening it, with nothing typed, starts the person's own workspace in the app-data
place behind a tray or menu-bar item.

The workspace is in the app-data folder (`engine/app_dirs.py`), made the first time with no template, unless the
environment names another (`THIMBLEBY_WORKSPACE`). A second open while the app runs only brings the browser forward.
Everything goes through the same pieces `thimbleby serve` uses (`engine.cli.make_app`); this module adds the tray, the
one-instance lock and the folder."""

from __future__ import annotations

import os
import platform
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
    *,
    launch: Callable[..., None] | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Make the workspace when it isn't there, then run the tray loop on it until the person quits."""
    from engine import cli, launcher
    from engine.handover import open_or_hold
    from engine.local_guards import local_address_problem
    from engine.sides import word
    from engine.workspace import WorkspaceError, init_workspace, resolve

    if not (root / "config").is_dir():
        if root.exists() and any(root.iterdir()):
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

    (launch or launcher.launch)(
        build,
        cfg.server.port,
        ws.private_dir,
        title=word(cfg, "desktop.title"),
        labels={k: word(cfg, f"desktop.{k}") for k in ("open", "restart", "quit")},
        open_path=lambda: f"{prefix}/?token={ws.install_token()}",
        readiness_path=f"{prefix}/api/health",
        restart_waiting=waiting.is_set,
        restarted=waiting.clear,
        restart_requested=asked,
        quit_requested=finished,
    )


def main(environ: Mapping[str, str] | None = None, home: Path | None = None) -> int:
    """The frozen app's entry with no arguments. Returns the exit code; a failure is written to the logs folder."""
    root, logs = places(environ, home)
    try:
        start(root, environ=environ)
    except BaseException as err:
        if isinstance(err, SystemExit | KeyboardInterrupt):
            raise
        note_failure(logs)
        return 1
    return 0
