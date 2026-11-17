"""The row on Today that offers a newer version of the app (`engine.update_offer`): Later hides that version until a
newer one comes, with Undo. Installing the version is not here yet; the route for it says so in words."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import Ok
from engine import update_offer
from engine.worker import Events
from engine.workspace import Workspace


def build_update_router(ws: Workspace, events: Events) -> APIRouter:
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
        """Update to this version and restart. The install is not built yet, so it says so and changes nothing."""
        known(version)
        raise HTTPException(
            status_code=409,
            detail="Updating from here isn't ready yet. Download the new version from Everything that changed.",
        )

    return r
