"""The week ahead (design 6.32): the assistant's reading of the coming week, at the top of the Schedule's week and
in the Monday briefing.

Reading writes nothing. "Read the week again" queues one request that goes the usual way (estimate, the person's
go above the configured amount). Setting a row aside ("Not this week") is the person's own change, answered with what
it replaced so that sending that back is Undo, and it records a signal."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import (
    HandedOver,
    Ok,
    RecordRef,
    WeekAheadDayOffView,
    WeekAheadRestore,
    WeekAheadRowView,
    WeekAheadSetAside,
    WeekAheadSetAsideKept,
    WeekAheadView,
)
from engine import week_ahead
from engine.config import Config
from engine.storage import Store, StoreError
from engine.worker import Events, Worker
from engine.workspace import Workspace

#: The kinds of record a row can cite, in the order they are looked for.
_KINDS = ("action", "fact", "event", "snapshot", "glossary_entry")


def build_week_ahead_router(ws: Workspace, cfg: Config, store: Store, events: Events, worker: Worker) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/week-ahead")
    def get_week_ahead() -> WeekAheadView:
        """This week as the assistant read it, or its rows by rules while it hasn't."""
        with store.read_scope():
            view = store.read()
            card = week_ahead.card_of(ws, store, cfg, worker.now())
            rows = []
            for row in card.rows:
                kind = next((k for k in _KINDS if view.get(k, row.source) is not None), None)
                if kind is None:
                    continue
                rows.append(
                    WeekAheadRowView(
                        from_day=row.from_day,
                        to_day=row.to_day,
                        words=row.words,
                        kind=row.kind,  # type: ignore[arg-type]
                        link=RecordRef(kind=kind, id=row.source),
                        side=row.side,
                    )
                )
            return WeekAheadView(
                first=card.first,
                last=card.last,
                state=card.state,  # type: ignore[arg-type]
                sentence=card.sentence,
                rows=rows,
                request=card.request,
                estimate_usd=card.estimate_usd,
                waiting=card.waiting,
                read_again=card.state not in ("working", "needs_go"),
                days_off=[WeekAheadDayOffView(day=d, reason=r) for d, r in card.days_off],
                working_days=card.working_days,
            )

    @r.post("/week-ahead/read")
    def read_again() -> HandedOver:
        """Ask the assistant to read this week again."""
        try:
            request = week_ahead.read_again(store, cfg, worker.now())
        except StoreError as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        events.changed()
        worker.poke()
        return HandedOver(request=request)

    @r.post("/week-ahead/set-aside")
    def set_aside(body: WeekAheadSetAside) -> WeekAheadSetAsideKept:
        """Leave one thing out of this week's rows ("Not this week"). Sending `previous` to restore is Undo."""
        previous = week_ahead.set_aside(store, cfg, worker.now(), body.source)
        events.changed()
        return WeekAheadSetAsideKept(previous=previous)

    @r.post("/week-ahead/restore")
    def restore(body: WeekAheadRestore) -> Ok:
        """Take back "Not this week": the week's set-aside list as `previous` had it."""
        week_ahead.restore(store, cfg, worker.now(), body.previous)
        events.changed()
        return Ok(ok="restored")

    return r
