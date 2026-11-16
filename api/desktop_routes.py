"""The installed Mac app's removal card (Settings, Advanced): what it says, "Open the folder" and "Quit and show the
app". Only on the computer the app runs on, and only for the installed Mac app; anywhere else the card is not offered
and the actions are refused. Nothing is deleted."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import RemovalView
from engine import app_removal
from engine.config import Config
from engine.launcher import InstanceLock, ask_to_show
from engine.legacy_names import private_dir
from engine.workspace import Workspace


def build_desktop_router(
    ws: Workspace, cfg: Config, current: Callable[[], app_removal.Removal] | None = None
) -> APIRouter:
    r = APIRouter(prefix="/api/desktop")
    here = current or (lambda: app_removal.current(os.environ, Path.home()))

    def removal() -> app_removal.Removal:
        found = here()
        if cfg.server.mode != "local" or not found.available:
            raise HTTPException(status_code=403, detail="Removing the app is something a Mac does on its own.")
        return found

    @r.get("/removal")
    def view() -> RemovalView:
        """Whether the removal card shows, and the folder the work stays in."""
        found = here()
        shown = cfg.server.mode == "local" and found.available
        return RemovalView(available=shown, folder=str(found.folder) if shown and found.folder else "")

    @r.post("/removal/open-folder", status_code=204)
    def open_folder() -> None:
        if not app_removal.open_folder(removal()):
            raise HTTPException(status_code=409, detail="The folder is not there yet.")

    @r.post("/removal/show-app", status_code=204)
    def show_app(background: BackgroundTasks) -> None:
        """Show the app in Finder, then quit it by the menu's own path once the answer is sent."""
        found = removal()
        app_removal.show_app(found)

        def quit_app() -> None:
            port = InstanceLock(private_dir(ws.root)).control_port()
            if port is not None:
                ask_to_show(port, ws.install_token(), what="quit")

        background.add_task(quit_app)

    return r
