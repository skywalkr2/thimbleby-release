"""The real `cockpit serve`, with one test-only route beside the app, for browser tests that need time to have passed.

    uv run python -m tests.e2e_serve serve -w <workspace> --port 8768 --no-open

Everything is the serve command's own (a restart starts this same program again); the app is the one the command
builds. The route is added around it and exists only here, never in the app:

- `POST /__e2e/age-runs` with `{"account": <account>, "minutes": N}` moves every read the watcher recorded for the
  sources of that account back in time by N minutes, as if they had been made that long ago. A failure becomes a line
  on Today only once it has lasted longer than the source's read interval times `watch.unread_gap_factor`, which a
  browser test cannot wait for. It answers with the number of reads moved.
- `POST /__e2e/offer-people` with `{"count": N, "from": K}` makes N people the assistant offered to add (as a look at
  who the person deals with leaves them), numbered from K, so a browser test can have a look's people arrive after
  setup. It answers with their names.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from engine.storage import WriteContext
from tests import e2e_stall_watch


def age_runs(store: Any, source_ids: list[str], minutes: float) -> int:
    """Move the start of every read recorded for these sources back by `minutes`; returns how many were moved."""
    moved = 0
    ctx = WriteContext(actor="watcher", trust="trusted", op="e2e.age-runs")
    with store.transaction() as tx:
        for source_id in source_ids:
            for run in tx.find("watch_run", {"source": source_id}):
                started = datetime.fromisoformat(str(run.data["started_at"])) - timedelta(minutes=minutes)
                tx.update("watch_run", run.id, {"started_at": started.isoformat()}, ctx, read_version=run.version)
                moved += 1
    return moved


def offer_people(store: Any, count: int, first: int = 1) -> list[str]:
    """Make `count` offers of people to add, numbered from `first`, as a look at who the person deals with does."""
    ctx = WriteContext(actor="engine", trust="trusted", op="e2e.offer-people")
    names = []
    with store.transaction() as tx:
        for n in range(first, first + count):
            name = f"Offered Person {n}"
            tx.create(
                "person_offer",
                {
                    "name": name,
                    "address": f"offered{n}@example.com",
                    "why": "Writes to you most weeks, and you reply within a day.",
                    "from_them": 6 + n,
                    "to_them": 3,
                    "status": "offered",
                    "offered_at": datetime.now().astimezone().isoformat(),
                },
                ctx,
            )
            names.append(name)
    return names


def with_routes(create_app: Any) -> Any:
    """`create_app`, returning the same app with the test route in front of it (the app's own state is kept)."""

    def create(ws: Any, cfg: Any, token: str, **kwargs: Any) -> Any:
        # The browser tests' own helpers send the harness's token as the bearer and open the page with it, so the app
        # takes that token as its install token and also pins it as a session value (the product never does).
        token = os.environ.get("E2E_INSTALL_TOKEN", token)
        app = create_app(ws, cfg, token, **kwargs)
        app.state.sessions.pin(token)
        # A silent stall in reading is written down when it happens (only when the run names a folder for it).
        e2e_stall_watch.start(app.state.worker, app.state.store)

        async def age(request: Any) -> JSONResponse:
            data = await request.json()
            account, minutes = data.get("account"), data.get("minutes")
            if not isinstance(account, str) or not isinstance(minutes, int | float) or isinstance(minutes, bool):
                return JSONResponse({"detail": "an account and a number of minutes are required"}, status_code=400)
            ids = [s.id for s in cfg.watch.sources if s.account == account]
            return JSONResponse({"moved": age_runs(app.state.store, ids, minutes), "sources": ids})

        async def offer(request: Any) -> JSONResponse:
            data = await request.json()
            count, first = data.get("count"), data.get("from", 1)
            if not isinstance(count, int) or isinstance(count, bool) or not isinstance(first, int) or count < 1:
                return JSONResponse({"detail": "a count of people to offer is required"}, status_code=400)
            names = offer_people(app.state.store, count, first)
            app.state.events.changed()
            return JSONResponse({"names": names})

        async def server_now(_request: Any) -> JSONResponse:
            # The server's clock now, in milliseconds, so a page can follow it (web/e2e/test.ts), and what the app
            # waits for a restart for ("code" when its own files changed while it ran): a failed test says so.
            return JSONResponse({"now": time.time() * 1000, "restart_for": list(app.state.worker.restart_for)})

        @asynccontextmanager
        async def lifespan(_outer: Any) -> Any:
            async with app.router.lifespan_context(app):
                yield

        outer = Starlette(
            routes=[
                Route("/__e2e/age-runs", age, methods=["POST"]),
                Route("/__e2e/offer-people", offer, methods=["POST"]),
                Route("/__e2e/now", server_now),
                Mount("/", app=app),
            ],
            lifespan=lifespan,
        )
        outer.state.worker = app.state.worker
        outer.state.store = app.state.store
        outer.state.events = app.state.events
        return outer

    return create


def main() -> int:
    import api.app
    from engine.cli import main as cockpit

    api.app.create_app = with_routes(api.app.create_app)
    if moment := os.environ.get("E2E_CLOCK_AT"):
        # The app's clock starts at this moment (an ISO 8601 moment in UTC) and keeps ticking, so a browser test can run
        # the app at a given hour; the made-up services start theirs at the same moment from the same variable.
        import time_machine

        time_machine.travel(datetime.fromisoformat(moment.replace("Z", "+00:00")), tick=True).start()
    return cockpit(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
