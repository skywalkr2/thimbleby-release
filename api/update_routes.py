"""The rows on Today about the app's own version (`engine.update_offer`, `engine.app_update`): the offer of a newer one
(Update and restart, Later with Undo) and the note that an update finished. The install starts the update from the
installed app's window; a copy that isn't the installed app has no install."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from api.schemas import Ok
from engine import app_update, update_offer
from engine.sides import word
from engine.worker import Events
from engine.workspace import Workspace


def build_update_router(
    ws: Workspace, events: Events, cfg, on_update: Callable[[str], None] | None = None
) -> APIRouter:
    r = APIRouter(prefix="/api/update")

    def known(version: str) -> None:
        found = update_offer.offer(ws.private_dir)
        if found is None or found.version != version:
            raise HTTPException(status_code=404, detail="That version isn't on offer any more.")

    @r.post("/{version}/later")
    def put_off(version: str) -> Ok:
        """Hide the offer of this version; a newer version is offered again. Undo is POST /{version}/later/undo."""
        known(version)
        update_offer.later(ws.private_dir, version)
        events.changed()
        return Ok(ok=version)

    @r.post("/{version}/later/undo")
    def put_off_undo(version: str) -> Ok:
        """Take Later back: the offer is on Today again."""
        update_offer.later(ws.private_dir, version, on=False)
        events.changed()
        return Ok(ok=version)

    @r.post("/{version}/install")
    def install(version: str) -> Ok:
        """Update to this version and restart: the app's window shows the steps and the app ends when the new version
        takes over. Answers at once; the steps run on their own thread. Only the installed app can update itself."""
        known(version)
        if on_update is None:
            raise HTTPException(status_code=400, detail=word(cfg, "desktop.update.reason.not_installed"))
        on_update(version)
        return Ok(ok=version)

    @r.post("/updated/seen")
    def seen() -> Ok:
        """The person has seen that the app was updated: its line leaves Today."""
        app_update.mark_seen(ws)
        events.changed()
        return Ok(ok="updated")

    return r
