"""Delete the workspace and everything the app kept of it (design 12.4): the list of exactly what goes, and the deletion
for the list the person saw. Only on the computer the app runs on; it is never a hosted install's action. Once the
workspace is deleted the app has nothing to run on and stops."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import EraseDone, EraseFailedView, EraseIn, EraseItemView, ErasePlanView
from engine import erase
from engine.config import Config
from engine.storage import Store
from engine.worker import Worker
from engine.workspace import Workspace


def _view(item: erase.Item) -> EraseItemView:
    return EraseItemView(
        kind=item.kind, path=item.path, name=item.name, files=item.files, bytes=item.bytes, commits=item.commits
    )


def build_erase_router(
    ws: Workspace, cfg: Config, store: Store, worker: Worker, on_erased: Callable[[], None] | None = None
) -> APIRouter:
    r = APIRouter(prefix="/api")

    def local_only() -> None:
        if cfg.server.mode != "local":
            raise HTTPException(status_code=403, detail="A workspace is deleted on the computer it runs on.")

    @r.get("/erase")
    def erase_plan() -> ErasePlanView:
        """What deleting the workspace would remove, each with its files and size, and what stays."""
        local_only()
        found = erase.plan(ws, cfg)
        return ErasePlanView(
            name=found.name,
            items=[_view(i) for i in found.items],
            stays=[_view(i) for i in found.stays],
            token=found.token,
        )

    @r.post("/erase")
    def erase_all(body: EraseIn, background: BackgroundTasks) -> EraseDone:
        """Delete what the list with this token shows. The app lets go of its database first, and stops once the answer
        is sent."""
        local_only()

        def let_go() -> None:
            worker.stop()
            store.close()

        try:
            result = erase.erase(ws, cfg, body.token, before=let_go)
        except erase.EraseRefused as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        if on_erased is not None:
            background.add_task(on_erased)
        return EraseDone(removed=len(result.removed), failed=[EraseFailedView(path=p, why=w) for p, w in result.failed])

    return r
