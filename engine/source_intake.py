"""A newly added source is taken in quietly (design 6.32).

The first read of a source with `first_run: intake` notes everything it holds, then hands the assistant what is worth
taking in: the mail of the last `first_run_days`, and every item of any other kind of source. Nothing is reported as new
one by one. The requests it makes carry `intake: <source id>`; they are priced together as one total and either start by
themselves (the total is not above `ai.budgets.confirm_above_usd`, and is known unless unpriced runs need no go) or wait
for one go, which is one line on Today. Their results are gathered into one line and one list to look over, not a line
each, until the person opens the list. Every open item found is followed from then on, whatever its age: the records the
assistant makes from it are ordinary records. Age only decides whether something is taken in at all.

The date before which a source's mail wasn't looked at is kept on the source's first `watch_run` (`looked_back_to`).
The person can ask for a look further back: the older mail the connector already returned (its snapshots) is taken in
the same way, under the same go rules, and the date moves.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine import catch_up, watch
from engine.connectors import OlderCount
from engine.local_day import day_of
from engine.net import AnswerTooLarge
from engine.storage import StoreError, WriteContext

log = logging.getLogger(__name__)

#: A look that takes in fewer than this fraction of the count the source gave says so.
SHORT_FRACTION = 3

#: What the requests of an intake wait on until the person's go; Today gathers them into one line for the source.
WAITING = "Taking in this source waits for you to start it."

_ENGINE = WriteContext(actor="engine", trust="trusted", op="intake.take_in")
_GO = WriteContext(actor="pm", trust="trusted", op="intake.go")
_SEEN = WriteContext(actor="pm", trust="trusted", op="intake.seen")
_MOVED = WriteContext(actor="engine", trust="trusted", op="intake.look_back")

#: The kinds of stop a read of older mail carries on from by itself; any other kind (a sign-in the service withdrew,
#: access refused, a message too large) is the person's to act on, and the account's own state says so.
CONTINUES = ("throttled", "outage", "offline")

#: How far past now a message's time may be and still count as received.
_SKEW = timedelta(minutes=5)


def waits_on_go(request: dict[str, Any]) -> bool:
    """Whether a request's data says it is part of a source's intake waiting for the person's go."""
    return (
        request.get("state") == "needs_you"
        and request.get("approval") == "required"
        and request.get("waiting") == WAITING
        and bool(request.get("intake"))
        and not request.get("dismissed")
    )


def unfinished(request: dict[str, Any]) -> bool:
    """Whether an intake request is still to be done: waiting its turn, running, or waiting for a go (the intake's
    own, or the first one in the workspace). A request that stopped, failed or has its result is finished."""
    from engine.dispatcher import waits_on_first_go

    return request.get("state") in ("queued", "running") or waits_on_go(request) or waits_on_first_go(request)


# ---- the window ---------------------------------------------------------------------------------------------


def _start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _when(data: dict[str, Any]) -> datetime | None:
    """When a mail item was received (else when it changed), as a moment with a zone; None when it says neither."""
    from engine.connectors import moment

    stamp = (data.get("message") or {}).get("received") or data.get("changed_at")
    if not stamp:
        return None
    try:
        at = moment(stamp)
    except (TypeError, ValueError):
        return None
    if not isinstance(at, datetime):
        at = _start(at)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def messages_looked_at(view: Any, source_id: str, back_to: date | None, now: datetime) -> int:
    """How many mail items a source holds that its first read looked at: received from the start of `back_to` (no
    start: any day) up to now, whatever became of them afterwards. Items that have gone from the source don't count."""
    accept = _in_window(back_to, None, now)
    return sum(
        1
        for snap in view.find("snapshot", {"source": source_id})
        if snap.data.get("message") and not snap.data.get("gone") and not snap.data.get("deleted") and accept(snap.data)
    )


def looked_back_to(source: Any, items: list[Any], now: datetime, capped: bool = False) -> date | None:
    """The day before which a source's mail isn't looked at by its first read: `first_run_days` before the read. None
    for a source that holds no mail (any other kind of source is taken in whole)."""
    mail = [item for item in items if getattr(item, "message", None) is not None]
    if not mail:
        return None
    window = (now - timedelta(days=source.first_run_days)).date()
    # A read that stopped at its cap (the connector says so) looked back only as far as the oldest message it returned,
    # so the date says that day, the same day a look further back starts from. Any other read looked at the window.
    if not capped:
        return window
    days = [at.astimezone(UTC).date() for item in mail if (at := _item_when(item)) is not None]
    return max(window, min(days)) if days else window


def _item_when(item: Any) -> datetime | None:
    """When a mail item was received (else when it changed), as a moment with a zone; None when it says neither."""
    return _when({"message": {"received": getattr(item.message, "received", None)}, "changed_at": item.changed_at})


def _in_window(back_to: date | None, until: date | None, now: datetime) -> Callable[[dict[str, Any]], bool]:
    """Which snapshots are taken in: mail received from the start of `back_to` (and before the start of `until`, or
    before now when there is none); everything that isn't mail when there is no `until`."""

    def accept(data: dict[str, Any]) -> bool:
        if not data.get("message"):
            return until is None  # another kind of item is taken in whole, once, by the first read
        at = _when(data)
        if at is None:
            return False
        if back_to is not None and at < _start(back_to):
            return False
        return at < _start(until) if until is not None else at <= now + _SKEW

    return accept


# ---- taking a source in -------------------------------------------------------------------------------------


def take_in(
    ws: Any, store: Any, cfg: Any, source: Any, now: datetime, router: Any = None, back_to: date | None = None
) -> list[str]:
    """Take in a source's first read: hand in what the window takes, held for one go, price it as one total, and start
    it at once when the total is not above the amount to confirm and is known (or unpriced runs need no go). Returns
    the requests made."""
    return _take(ws, store, cfg, source, now, router, _in_window(back_to, None, now), go=True)


def _take(
    ws: Any,
    store: Any,
    cfg: Any,
    source: Any,
    now: datetime,
    router: Any,
    accept: Callable[[dict[str, Any]], bool],
    older: bool = False,
    go: bool = False,
) -> list[str]:
    """Hand in the window the source takes, held for one go. With `go` (a source's first window) connecting the source
    is the go: the window is started at once whatever its estimate, and the worker sorts its mail; the daily and
    monthly stops of the spending limits are the cap, and nothing asks the person to start the reading."""
    made = watch._hand_in_window(
        ws,
        store,
        cfg,
        source.id,
        now,
        router,
        accept,
        extra={
            "intake": source.id,
            **({"intake_older": True} if older else {}),
            "state": "needs_you",
            "approval": "required",
            "waiting": WAITING,
        },
        sort=False,  # the assistant's sorting is part of the one total: it runs when the intake starts
    )
    view = store.read()
    held = [r for r in made if waits_on_go(view.get("request", r).data)]
    if not held:
        return made
    catch_up._price(ws, store, cfg, router, held, now, _ENGINE)
    if go:
        grant_go(ws, store, cfg, source.id, router, now)
        return made
    cost = waiting_cost(ws, store, cfg, source.id, router)
    # A run whose price isn't known always waits for the go; one on a flat account only when the person asked for a go
    # before those too, as single runs do. Starting without asking is decided on the most it could cost, never on the
    # likely figure: the configured amount is a ceiling on what starts unasked.
    priced_enough = cost.unpriced == 0 or not any(_go_for_price(ws, store, cfg, router, r, now) for r in held)
    if cost.count and priced_enough and (cost.at_most or 0.0) <= cfg.ai.budgets.confirm_above_usd:
        # Sorting first, while they are held, so mail it sets aside never queues; with no go given, its own checks hold.
        watch.sort_before_first_go(ws, store, cfg, router, now, only=source.id, go=False)
        _release(store, source.id, now)
    return made


def _go_for_price(ws: Any, store: Any, cfg: Any, router: Any, request_id: str, now: datetime) -> bool:
    """Whether a held request has no price that lets it start without the person's go."""
    import os

    from engine.ai import pricing
    from engine.ai.router import Router
    from engine.dispatcher import price_state_request

    found = store.read().get("request", request_id)
    if found is None or found.data.get("estimate_usd") is not None:
        return False
    router = router() if callable(router) else router or Router(cfg, store, env=os.environ)
    try:
        state = price_state_request(ws, store, cfg, router, request_id, now)
    except Exception:  # a run that can't be priced is shown as unpriced, never blocks the others
        state = pricing.UNKNOWN
    return pricing.go_needed(cfg, state)


def _release(store: Any, source_id: str, now: datetime) -> int:
    """Start the intake's held requests without a go: the total is known and below the amount to confirm, so they
    are queued like any other work (the first-go and per-run checks still apply when each is processed)."""
    started = 0
    with store.transaction() as tx:
        for req in tx.list("request"):
            if waits_on_go(req.data) and req.data.get("intake") == source_id:
                tx.update(
                    "request",
                    req.id,
                    {"state": "queued", "approval": None, "waiting": watch.STARTING},
                    _ENGINE,
                    read_version=req.version,
                )
                started += 1
    return started


def waiting(view: Any, source_id: str | None = None) -> list[Any]:
    """The requests held for an intake's go, oldest first; of one source, or of every source."""
    held = [
        r
        for r in view.list("request")
        if waits_on_go(r.data) and (source_id is None or r.data.get("intake") == source_id)
    ]
    return sorted(held, key=lambda r: str(r.data.get("created_at")))


@dataclass(frozen=True)
class WaitingCost:
    """What a source's go would start: `count` requests, about `likely` and at most `at_most` USD together with the
    sorting for their mail (None when nothing has a price) and how many runs have no price."""

    count: int
    likely: float | None
    at_most: float | None
    unpriced: int


def waiting_cost(ws: Any, store: Any, cfg: Any, source_id: str, router: Any = None) -> WaitingCost:
    """What a source's intake would start, in two figures. The most is every held run at its own estimate plus the
    sorting at the full price. The likely price reads in full only the share of the mail awaiting sorting that the
    source's sorting keeps (`read_estimate.kept_share`), with the runs' stable part at the account's cached price
    (the ratio the formula gives for a packet this source's requests built), plus the sorting priced the same way."""
    held = waiting(store.read(), source_id)
    if not held:
        return WaitingCost(0, None, None, 0)
    priced = [r.data["estimate_usd"] for r in held if r.data.get("estimate_usd") is not None]
    _runs, sort_likely, sort_most, sort_unpriced = watch.first_go_sorting_range(ws, store, cfg, router, only=source_id)
    read_most = sum(priced)
    read_likely = read_most
    if priced:
        from engine import read_estimate

        router = read_estimate.router_for(cfg, store, router)
        ids = {r.id for r in held}
        through = sum(
            1
            for items in watch._awaiting_sorting(ws, store, cfg, source_id).values()
            for it in items
            if it[0].id in ids
        )
        kept = min(len(held), through * read_estimate.kept_share(store, cfg, source_id) + len(held) - through)
        range_ = read_estimate.read_range(ws, store, cfg, router, source_id, kept, len(held), datetime.now(UTC))
        if range_ is not None and range_[1] > 0:
            read_likely = read_most * range_[0] / range_[1]
    total_likely = read_likely + (sort_likely or 0.0)
    total_most = read_most + (sort_most or 0.0)
    known = bool(priced) or sort_likely is not None
    return WaitingCost(
        len(held),
        round(total_likely, 4) if known else None,
        round(total_most, 4) if known else None,
        len(held) - len(priced) + sort_unpriced,
    )


def total_waiting(ws: Any, store: Any, cfg: Any, source_id: str, router: Any = None) -> tuple[int, float | None, int]:
    """What a source's intake would start: how many requests wait for its go, about what the ones with a price cost
    together with the sorting run for their mail (None when nothing has a price) and how many runs have no price.
    `waiting_cost` also gives the most it could cost."""
    cost = waiting_cost(ws, store, cfg, source_id, router)
    return cost.count, cost.likely, cost.unpriced


def grant_go(ws: Any, store: Any, cfg: Any, source_id: str, router: Any = None, now: datetime | None = None) -> int:
    """The person's go for a source's intake: every request held for the go is approved and queued, and the ones whose
    mail was never sorted are marked `sort_pending`, so the worker sorts them under this go before any of them runs
    (what the sorting sets aside never runs). Nothing here asks the assistant, so the go answers at once; a write that
    clashes with another (the reading's own) is made again, never shown. Returns how many were."""
    from engine.dispatcher import GO_TRIES
    from engine.storage import ConflictError

    for attempt in range(GO_TRIES):
        unsorted = watch.awaiting_sorting_ids(ws, store, cfg, source_id)
        started = 0
        try:
            with store.transaction() as tx:
                for req in tx.list("request"):
                    if waits_on_go(req.data) and req.data.get("intake") == source_id:
                        changes: dict[str, Any] = {
                            "approval": "granted",
                            "state": "queued",
                            "waiting": None,
                            "cause": None,
                        }
                        if req.id in unsorted:
                            changes["sort_pending"] = True
                        tx.update("request", req.id, changes, _GO, read_version=req.version)
                        started += 1
            return started
        except ConflictError:
            if attempt == GO_TRIES - 1:
                raise
    return 0


# ---- the results, as one list -------------------------------------------------------------------------------


def unseen(view: Any) -> dict[str, list[Any]]:
    """The requests of each source's intake whose results the person hasn't opened yet, by source id."""
    found: dict[str, list[Any]] = {}
    for req in view.marked("request", "intake"):
        d = req.data
        if d.get("intake") and not d.get("intake_seen") and not d.get("dismissed"):
            found.setdefault(d["intake"], []).append(req)
    return found


def mark_seen(store: Any, source_id: str) -> list[str]:
    """The person opened the list of what an intake found: its requests show on Today one by one again if they still
    need a look. Returns the requests marked, for Undo."""
    marked: list[str] = []
    with store.transaction() as tx:
        for req in tx.list("request"):
            d = req.data
            if d.get("intake") == source_id and not d.get("intake_seen") and not d.get("dismissed"):
                tx.update("request", req.id, {"intake_seen": True}, _SEEN, read_version=req.version)
                marked.append(req.id)
    return marked


def mark_unseen(store: Any, request_ids: list[str]) -> int:
    """Undo `mark_seen` for these requests. Returns how many were put back."""
    back = 0
    with store.transaction() as tx:
        for request_id in request_ids:
            req = tx.get("request", request_id)
            if req is not None and req.data.get("intake") and req.data.get("intake_seen"):
                tx.update("request", req.id, {"intake_seen": False}, _SEEN, read_version=req.version)
                back += 1
    return back


# ---- how far back a source was looked at --------------------------------------------------------------------


def intake_run(view: Any, source_id: str) -> Any | None:
    """The read of a source that took it in quietly and noted how far back it looked, or None."""
    runs = [r for r in view.find("watch_run", {"source": source_id}) if r.data.get("looked_back_to")]
    return runs[0] if runs else None


def back_to_of(view: Any, source_id: str) -> date | None:
    """The day before which a source's mail wasn't looked at, or None (nothing was taken in, or no mail)."""
    run = intake_run(view, source_id)
    return day_of(run.data["looked_back_to"], UTC) if run else None


def days_taken(view: Any, source_id: str) -> int | None:
    """How many days before its first read a source's mail was looked at (what the intake's line says), None for a
    source with no mail."""
    run = intake_run(view, source_id)
    if run is None:
        return None
    # The look-back date is a UTC day (`looked_back_to`), so the read is counted in UTC days too.
    read = datetime.fromisoformat(str(run.data["started_at"])).date()
    return max(1, (read - day_of(run.data["looked_back_to"], UTC)).days)


# ---- looking further back -----------------------------------------------------------------------------------


@dataclass
class LookBack:
    """What looking further back would take in, or did: the items, what they cost, and how far the source reaches."""

    days: int
    from_date: date  # the day asked for
    count: int = 0
    estimate_usd: float | None = None  # about what reading them costs
    estimate_max_usd: float | None = None  # the most it could cost: "at most"
    unpriced: int = 0
    available_from: date | None = None  # the oldest mail the source has returned, when it is later than asked
    reaches: bool = True  # the source holds mail as far back as asked
    started: bool = False  # taken in and started at once (False: held for the go, or nothing to take in)
    taken: int = 0
    capped: bool = False  # the count stopped at the most one look asks for, so there may be more: "at least"
    estimate: bool = False  # the source's count is its own rough figure: "about"
    skipped: dict[str, int] = field(default_factory=dict)  # what the look couldn't read, by kind
    expected: int = 0  # after a look: how many the source said it holds of those days, before it was asked to read
    expected_estimate: bool = False  # that figure was an estimate
    gave: int = 0  # after a look: how many messages the source gave (those it couldn't read among them)
    short: bool = False  # after a look: the source gave fewer than a third of what it said it holds
    stopped: str | None = None  # after a look the service slowed down or failed partway: the kind of stop
    continues_at: str | None = None  # when the rest is read by itself; None when it waits for the person or ended
    gave_up: bool = False  # the read ran out of tries and waits for the person to continue it
    unknown: bool = False  # the source could not say how many there are: no number is shown, and the read goes on


def _candidates(ws: Any, store: Any, cfg: Any, source: Any, accept: Callable[[dict[str, Any]], bool]) -> list[Any]:
    """The snapshots a look further back would hand in: mail in the window that was never handed in and that no rule
    closes."""
    from engine.triage import classify

    view = store.read()
    handed = {
        (s.data.get("watched") or {}).get("key")
        for s in view.list("source")
        if (s.data.get("watched") or {}).get("source") == source.id
    }
    found = []
    messages = watch.MessageIndex(view)
    for snap in view.find("snapshot", {"source": source.id}):
        data = snap.data
        if data.get("gone") or data.get("deleted") or data.get("set_aside") or data["key"] in handed:
            continue
        if not accept(data) or messages.taken_elsewhere(snap):
            continue
        item = watch.item_of_snapshot(ws, data)
        closed, kept = classify(store, cfg, watch._change(cfg, source, item, "new", None))
        if closed is None or kept:
            found.append(snap)
    return found


def _asker(store: Any, source: Any) -> tuple[Any, type] | None:
    """How a source is asked for older mail, and the settings model it reads with: a core mail connector that reads
    older mail, or a plugin's connector that said it can (`older=`). None when the source can't be asked, which is
    when it is never offered a look further back."""
    from engine.connectors import CORE, older_mail

    asking = older_mail(source.connector)
    if asking is not None:
        return asking, CORE[source.connector].settings
    plugins = getattr(store, "plugins", None)
    connector = plugins.connectors().get(source.connector) if plugins is not None else None
    if connector is None or connector.older is None:
        return None
    return plugins.older_mail(connector, source.account), connector.settings


def can_look_back(source: Any, store: Any = None) -> bool:
    """Whether the source can be asked for mail older than its first read took: a core mail connector that reads older
    mail, or a plugin's connector that declares it can (`store` says which plugins run). Any other source is never
    offered a look further back."""
    from engine.connectors import older_mail

    if getattr(source, "role", None) == "deleted":
        return False  # deleted mail is read over the first window only, never further back
    if older_mail(source.connector) is not None:
        return True
    return store is not None and _asker(store, source) is not None


def _older_context(ws: Any, cfg: Any, now: datetime) -> Any:
    from engine.connectors import ConnectorContext

    return ConnectorContext(
        workspace_root=ws.root, now=now, timezone=cfg.workspace.user.timezone, hosted=cfg.server.mode == "hosted"
    )


def _remote_range(store: Any, source_id: str, asked: date, old: date, available: date | None) -> tuple[date, date]:
    """The days the source itself is asked about: from the day asked up to the oldest day the app already holds."""
    return asked, min(old, available) if available is not None else old


def _remote_count(
    ws: Any, store: Any, cfg: Any, source: Any, since: date, before: date, now: datetime, limit: int | None = None
) -> OlderCount | None:
    """How many older messages the source would give for these days, within the setting's limit, and whether that is
    only its estimate; 0 when it can't be asked or the days are empty; None when the source could not say (any
    `ConnectorError`: a wait, an outage, a sign-in). A count that can't be had never blocks or fails a read: the read
    goes on with no number. A core mailbox reads no message to say; a plugin's connector that gives no count is read
    for it."""
    from engine.connectors import ConnectorError

    asker = _asker(store, source)
    if asker is None or since >= before:
        return OlderCount(0)
    asking, model = asker
    settings = model.model_validate(source.settings)
    try:
        found = asking.count(
            settings, since, before, limit or cfg.watch.look_back_max_items, _older_context(ws, cfg, now)
        )
    except ConnectorError:
        return None
    return found if isinstance(found, OlderCount) else OlderCount(found)


def _item_day(item: Any) -> date | None:
    """The day a message was received, None when it says none."""
    received = getattr(getattr(item, "message", None), "received", None)
    at = _when({"message": {"received": received}}) if received else None
    return at.astimezone(UTC).date() if at is not None else None


@dataclass
class Fetched:
    """What a read of older mail gave: how many messages (those it couldn't read among them), what it skipped, and, when
    the service slowed it down or failed partway, the error and the day the next page would have ended on: the days from
    there up to where the read began were read whole, and the rest of the range is still to read."""

    count: int
    skipped: dict[str, int] = field(default_factory=dict)
    stop: Any = None
    end: date | None = None
    more: bool = False  # the slice ended after its pages with more of the range still to read, from `end` on


def _fetch_older(
    ws: Any,
    store: Any,
    cfg: Any,
    source: Any,
    since: date,
    before: date,
    now: datetime,
    limit: int | None = None,
    carrying_on: bool = False,
    page: int | None = None,
    pages: int | None = None,
) -> Fetched:
    """Ask the source for its older mail of these days, within the setting's limit, and note it the way a first read
    notes what it doesn't hand in. `page` is the size of a page (the look further back's setting by default); `pages`
    ends a slice after that many pages that moved on, with `more` set when the range is not finished. A message the
    source couldn't read never stops the rest. When the service slows the read down or fails after some pages, what
    was read stays and the answer says where it stopped (`stop`, `end`); a
    failure before any page was read raises, unless the read is carrying on from an earlier stop."""
    from engine.connectors import ConnectorError, Poll, skipped_counts

    asker = _asker(store, source)
    if asker is None or since >= before:
        return Fetched(0)
    asking, model = asker
    settings = model.model_validate(source.settings)
    ceiling = limit or page or cfg.watch.look_back_max_items
    page = min(page or cfg.watch.look_back_max_items, ceiling)
    seen: set[str] = set()
    skipped: dict[str, int] = {}
    end = before
    size = page
    moved = 0
    while True:
        try:
            answer = asking.read(settings, since, end, size, _older_context(ws, cfg, now))
        except ConnectorError as err:
            # Before anything was read, a stop the person must deal with (a sign-in, a missing folder) is said at once;
            # a service that asked to wait, was down or couldn't be reached keeps the choice and carries on later.
            if not seen and not carrying_on and err.kind not in CONTINUES:
                raise StoreError(older_failure(err)) from None
            return Fetched(len(seen), skipped, err, end)
        items, unreadable = (answer.items, answer.unreadable) if isinstance(answer, Poll) else (answer, [])
        stopped = answer.stopped if isinstance(answer, Poll) else None
        if stopped is not None and not (seen or items or unreadable or carrying_on) and stopped.kind not in CONTINUES:
            raise StoreError(older_failure(stopped))
        new_items = [i for i in items if i.key not in seen]
        new_unreadable = [u for u in unreadable if u.key not in seen]
        seen.update(i.key for i in new_items)
        seen.update(u.key for u in new_unreadable)
        watch._compare(ws, store, cfg, source, Poll(list(new_items), complete=False), now, True)
        watch._tell_unreadable(store, cfg, source, new_unreadable)
        for kind, n in skipped_counts(new_unreadable).items():
            skipped[kind] = skipped.get(kind, 0) + n
        if stopped is not None:
            # The read was slowed down or failed partway through the page: what it gave stays, and the days from the
            # oldest item's day on were not read whole, so the next try starts on that day again.
            days = [d for d in map(_item_day, items) if d is not None]
            following = min(days) + timedelta(days=1) if days else end
            return Fetched(len(seen), skipped, stopped, following if new_items and following < end else end)
        # A page that came back full may have more behind it. The next page ends on the day after its oldest message
        # (that day again, since a page can stop part way through it). When that day is no earlier than this page's
        # end, one day holds more than a page, so the same range is asked again for more, up to the ceiling; a short
        # page or the ceiling ends the read.
        if len(items) + len(unreadable) < size or len(seen) >= ceiling:
            break
        days = [d for d in map(_item_day, items) if d is not None]
        following = min(days) + timedelta(days=1) if days else end
        if new_items and following < end:
            end, size = following, page
            moved += 1
            if pages is not None and moved >= pages and end > since:
                return Fetched(len(seen), skipped, None, end, more=True)
        elif size >= ceiling:
            break
        else:
            size = min(size * 2, ceiling)
        if end <= since:
            break
    return Fetched(len(seen), skipped)


def add_older_skipped(store: Any, source_id: str, counts: dict[str, int]) -> None:
    """Add what a read of older mail or of headers skipped to the source's first read, where the account's row reads
    it. Nothing is written for a read that skipped nothing, or for a source with no first read that took mail in."""
    run = intake_run(store.read(), source_id)
    if run is None or not counts:
        return
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        total = dict(current.data.get("older_skipped") or {})
        for kind, n in counts.items():
            total[kind] = total.get(kind, 0) + n
        tx.update("watch_run", run.id, {"older_skipped": total}, _MOVED, read_version=current.version)


def _source(cfg: Any, source_id: str) -> Any:
    source = next((s for s in cfg.watch.sources if s.id == source_id), None)
    if source is None:
        raise StoreError(f"there is no source {source_id}")
    return source


def _plan(store: Any, cfg: Any, source_id: str, days: int, exact: bool = False) -> tuple[date, date, date, date | None]:
    """The day the person asked for, the day the first look stopped at, the day the look will stop at and the oldest
    mail the source holds (None when it holds none). `exact` takes `days` as worked out from a reach (the full read's
    choice), not one of the look further back's choices."""
    old = back_to_of(store.read(), source_id)
    if old is None:
        raise StoreError("this source was not taken in with a look back, so there is nothing further to look at")
    if days not in cfg.watch.look_back_choices and not (exact and days >= 1):
        raise StoreError(f"{days} days is not one of the choices")
    return _plan_from(store, source_id, old - timedelta(days=days))


def _plan_from(store: Any, source_id: str, asked: date) -> tuple[date, date, date, date | None]:
    """`_plan` for a day already asked for: the day asked, the day the mail was looked at back to, the day the look will
    stop at and the oldest mail the source holds."""
    old = back_to_of(store.read(), source_id)
    if old is None:
        raise StoreError("this source was not taken in with a look back, so there is nothing further to look at")
    oldest = min(
        (
            at
            for s in store.read().find("snapshot", {"source": source_id})
            if s.data.get("message") and not s.data.get("gone") and (at := _when(s.data)) is not None
        ),
        default=None,
    )
    available = oldest.astimezone(UTC).date() if oldest is not None else None
    reaches = available is None or available <= asked
    return asked, old, asked if reaches else min(old, available or old), available


def look_back_preview(
    ws: Any,
    store: Any,
    cfg: Any,
    source_id: str,
    days: int,
    now: datetime | None = None,
    exact: bool = False,
    router: Any = None,
) -> LookBack:
    """What looking `days` further back than the source was looked at would take in: how many items, about what they
    cost and the most they could (`read_estimate.cost_of_reading`: the sorting for all of them, the full read of the
    share the sorting keeps, the account's cache; none when no price is known), and whether the source holds mail that
    far back. Writes nothing."""
    source = _source(cfg, source_id)
    asked, old, _new, available = _plan(store, cfg, source_id, days, exact)
    now = now or datetime.now(UTC)
    if not can_look_back(source, store):
        raise StoreError("this source can't be asked for older mail")
    found = _candidates(ws, store, cfg, source, _in_window(asked, old, now))
    limit = cfg.watch.full_read_max_items if exact else cfg.watch.look_back_max_items
    counted = _remote_count(ws, store, cfg, source, *_remote_range(store, source_id, asked, old, available), now, limit)
    remote = counted.count if counted is not None else 0
    count = len(found) + remote
    result = LookBack(days, asked, count, available_from=available if available and available > asked else None)
    result.unknown = counted is None
    # The source was asked: fewer than the limit means it holds nothing older than it gave.
    result.capped = remote >= limit
    result.estimate = counted is not None and counted.estimate and remote > 0
    result.reaches = result.available_from is None or not result.capped
    if result.reaches:
        result.available_from = None
    if count:
        from engine import read_estimate

        cost = read_estimate.cost_of_reading(ws, store, cfg, source, count, now, router)
        result.estimate_usd, result.estimate_max_usd, result.unpriced = cost.likely, cost.at_most, cost.unpriced
    return result


def look_further_back(
    ws: Any,
    store: Any,
    cfg: Any,
    source_id: str,
    days: int,
    now: datetime | None = None,
    router: Any = None,
    exact: bool = False,
    reach_days: int | None = None,
) -> LookBack:
    """Take in the older mail the source already returned, `days` further back than it was looked at, the same quiet
    way: marked as the source's intake, priced as one total with what is still held, held for the go or started by
    the same rule. The date it was looked back to moves to the day asked for, or to the oldest mail the source holds
    when that is later. The result says so when the source doesn't reach that far. When the service slows the read
    down or fails after some pages, what was read is taken in, the date moves only over the days read whole, and the
    rest carries on by itself (`continue_older_read`); `reach_days` is the full read's choice, kept with it."""
    now = now or datetime.now(UTC)
    source = _source(cfg, source_id)
    if not can_look_back(source, store):
        raise StoreError("this source can't be asked for older mail")
    with watch._read_lock(ws, source_id):
        asked, old, new, available = _plan(store, cfg, source_id, days, exact)
        limit = cfg.watch.full_read_max_items if exact else cfg.watch.look_back_max_items
        reach = _remote_range(store, source_id, asked, old, available)
        # What the source says it holds of these days, asked before it is read, so a read that gives far fewer says so.
        # Asked only of a source that counts without reading: one that reads to count would read everything twice.
        asker = _asker(store, source)
        counts = asker is not None and asker[0].counts
        said = (_remote_count(ws, store, cfg, source, *reach, now, limit) if counts else None) or OlderCount(0)
        return _read_older(ws, store, cfg, source, asked, reach, limit, said, now, router, reach_days, None, days)


def queue_look_further_back(
    ws: Any, store: Any, cfg: Any, source_id: str, days: int, now: datetime | None = None
) -> LookBack:
    """The look further back as the source's menu asks for it: the choice is recorded with the read still to do, on the
    source's first read, and the worker's lane reads it in slices (`reading_lane.run_slices`), so the answer returns at
    once and nothing is asked of the service here. A read already waiting is extended to the earlier day. Returns the
    queued look (`stopped` is "queued")."""
    now = now or datetime.now(UTC)
    source = _source(cfg, source_id)
    if not can_look_back(source, store):
        raise StoreError("this source can't be asked for older mail")
    asked, old, _new, available = _plan(store, cfg, source_id, days)
    since, before = _remote_range(store, source_id, asked, old, available)
    run = intake_run(store.read(), source_id)
    if run is None:
        raise StoreError("this source was not taken in with a look back, so there is nothing further to look at")
    queued = {
        "since": since.isoformat(),
        "before": before.isoformat(),
        "left": cfg.watch.look_back_max_items,
        "kind": "queued",
        "stopped_at": now.isoformat(),
        "tries": 0,
        "taken": 0,
        "reach": None,
        "at": now.isoformat(),
        "gave_up": False,
    }
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        waiting_read = current.data.get("older_read")
        if waiting_read:
            queued = {**waiting_read, "since": min(str(waiting_read["since"]), queued["since"])}
        tx.update("watch_run", run.id, {"older_read": queued}, _MOVED, read_version=current.version)
    result = LookBack(days=days, from_date=asked, reaches=True)
    result.stopped, result.continues_at = "queued", str(queued["at"]) if queued.get("at") else None
    return result


def _read_older(
    ws: Any,
    store: Any,
    cfg: Any,
    source: Any,
    asked: date,
    reach: tuple[date, date],
    limit: int,
    said: OlderCount,
    now: datetime,
    router: Any,
    reach_days: int | None,
    carried: dict[str, Any] | None,
    days: int = 0,
    pages: int | None = None,
) -> LookBack:
    """Read the range (or, with `pages`, one slice of it), take in what was read and move the date it was looked back
    to. `carried` is the earlier stop of a read being carried on. A full read (`reach_days`) asks in the larger pages of
    `watch.full_read_page_items`. Called with the source's read lock held."""
    source_id = source.id
    forget_full_read_counts(ws, source_id)
    page = cfg.watch.full_read_page_items if reach_days is not None else None
    fetched = _fetch_older(
        ws, store, cfg, source, *reach, now, limit, carrying_on=carried is not None, page=page, pages=pages
    )
    add_older_skipped(store, source_id, fetched.skipped)
    asked, old, new, available = _plan_from(store, source_id, asked)
    stop = fetched.stop
    if stop is None and not fetched.more:
        everything = fetched.count < limit  # the source gave all it holds of those days
        if everything:
            new = asked
            available = None
    elif fetched.end is not None:
        new = min(old, max(asked, fetched.end))  # only the days read whole are looked at
        available = None
    found = _candidates(ws, store, cfg, source, _in_window(asked, old, now))
    result = LookBack(days=days, from_date=asked, count=len(found))
    result.available_from = available if available and available > asked else None
    result.reaches = result.available_from is None
    result.skipped = fetched.skipped
    result.expected, result.expected_estimate, result.gave = said.count, said.estimate, fetched.count
    result.short = (
        said.count > 0
        and fetched.count * SHORT_FRACTION < said.count
        and said.count < limit
        and stop is None
        and not fetched.more
    )
    keys = {snap.data["key"] for snap in found}
    made = _take(
        ws,
        store,
        cfg,
        source,
        now,
        router,
        lambda data: data["key"] in keys,
        older=True,
        go=bool(carried and carried.get("go")),  # the person's pick is the go: a slice never waits to be started
    )
    result.taken = len(made)
    if made and carried and carried.get("go"):
        # The person's choice of this reach was also the go for what it brings: nothing of it waits for a second ask.
        grant_go(ws, store, cfg, source_id, router, now)
    view = store.read()
    held = [r for r in made if waits_on_go(view.get("request", r).data)]
    result.started = bool(made) and not held
    carry = _carry(cfg, stop, fetched, reach[0], limit, now, carried, reach_days, len(made))
    run = intake_run(view, source_id)
    if run is not None and (new < old or carry != (run.data.get("older_read") or None)):
        with store.transaction() as tx:
            current = tx.get("watch_run", run.id)
            changes: dict[str, Any] = {"older_read": carry}
            if carry is None:
                changes["older_finished_at"] = now.isoformat()  # the read ended: the look at people may look again
            if new < old:
                changes["looked_back_to"] = new.isoformat()
            tx.update("watch_run", run.id, changes, _MOVED, read_version=current.version)
    if stop is not None:
        result.stopped = stop.kind
        result.continues_at = carry["at"] if carry and carry.get("at") else None
        result.gave_up = bool(carry and carry.get("gave_up"))
    elif fetched.more:
        result.stopped = "reading"
    counted, total, unpriced = total_waiting(ws, store, cfg, source_id, router)
    result.estimate_usd, result.unpriced = total, unpriced
    return result


def _carry(
    cfg: Any,
    stop: Any,
    fetched: Fetched,
    since: date,
    limit: int,
    now: datetime,
    carried: dict[str, Any] | None,
    reach_days: int | None,
    taken: int,
) -> dict[str, Any] | None:
    """Where a read that stopped, or that ended a slice with more to read, carries on, kept on the source's first read:
    the days still to read, what is left of the limit, why it stopped, when it continues and how many times it has
    stopped in a row without getting further (a wait for the service never counts). None when the read finished, or
    stopped for a reason the person has to deal with."""
    if stop is None and not fetched.more:
        return None
    if stop is not None and (stop.kind not in CONTINUES or isinstance(stop, AnswerTooLarge)):
        return None
    if fetched.end is None:
        return None
    before = carried or {}
    progressed = taken > 0  # new items taken in: a page of messages already taken is no progress
    if stop is None:
        # A slice that ended with more to read: the next slice is due at once, and nothing was tried and failed.
        tries, kind = 0, "reading"
    elif stop.kind == "throttled":
        # A wait is a wait, never a try: it adds nothing to the stops in a row, and a read that is only ever asked to
        # wait is never given up on.
        tries, kind = (0 if progressed else int(before.get("tries", 0))), "throttled"
    else:
        # Stops in a row that got no further: after the last try the person decides.
        tries, kind = (1 if progressed else int(before.get("tries", 0)) + 1), stop.kind
    base: dict[str, Any] = {
        "since": since.isoformat(),
        "before": fetched.end.isoformat(),
        "left": max(1, limit - fetched.count),
        "kind": kind,
        # The refusing answer, kept as the service gave it (its status, the error kind and short reason code, its wait).
        **(
            {
                "status": stop.status,
                "reason": f"{stop.kind}:{stop.reason}" if stop.reason else stop.kind,
                "wait_seconds": stop.retry_after,
            }
            if stop is not None
            else {}
        ),
        "stopped_at": now.isoformat(),
        "tries": tries,
        "taken": int(before.get("taken", 0)) + taken,
        "reach": reach_days if reach_days is not None else before.get("reach"),
        **({"about": before["about"]} if before.get("about") else {}),
        **({"go": True} if before.get("go") else {}),
    }
    if stop is None:
        return {**base, "at": now.isoformat(), "gave_up": False}
    if tries > cfg.watch.older_read_tries:
        return {**base, "at": None, "gave_up": True}
    if stop.kind == "throttled":
        wait = stop.retry_after if stop.retry_after is not None else cfg.watch.older_read_throttle_minutes * 60
    else:
        wait = cfg.watch.older_read_retry_minutes * 60
    return {**base, "at": (now + timedelta(seconds=wait)).isoformat(), "gave_up": False}


def older_read_waiting(view: Any, source_id: str) -> dict[str, Any] | None:
    """Where a source's read of older mail stopped and waits to carry on, or None."""
    run = intake_run(view, source_id)
    return dict(run.data["older_read"]) if run is not None and run.data.get("older_read") else None


def older_read_due(view: Any, cfg: Any, now: datetime) -> list[str]:
    """The sources whose read of older mail stopped and whose time to carry on has come."""
    due = []
    for source in cfg.watch.sources:
        waiting_read = older_read_waiting(view, source.id)
        if waiting_read and waiting_read.get("at") and now >= datetime.fromisoformat(str(waiting_read["at"])):
            due.append(source.id)
    return due


def continue_older_read(
    ws: Any,
    store: Any,
    cfg: Any,
    source_id: str,
    now: datetime | None = None,
    router: Any = None,
    force: bool = False,
    pages: int | None = None,
) -> LookBack | None:
    """Carry on a read of older mail from where it stopped, under the source's read lock (nothing is done when it is
    being read already), when its time has come, or at once when the person asks (`force`, also after it gave up).
    `pages` reads one slice of that many pages and leaves the rest due at once (the worker's lane); none reads to the
    end. Returns what that pass did, or None when there was nothing to carry on."""
    now = now or datetime.now(UTC)
    source = _source(cfg, source_id)
    lock = watch._read_lock(ws, source_id)
    if not lock.acquire(blocking=False):
        return None
    try:
        waiting_read = older_read_waiting(store.read(), source_id)
        if waiting_read is None or not can_look_back(source, store):
            return None
        due = waiting_read.get("at")
        if not force and not (due and now >= datetime.fromisoformat(str(due))):
            return None
        reach = (date.fromisoformat(waiting_read["since"]), date.fromisoformat(waiting_read["before"]))
        if force:  # the person asked: it has another round of tries
            waiting_read = {**waiting_read, "tries": 0}
        return _read_older(
            ws,
            store,
            cfg,
            source,
            reach[0],
            reach,
            int(waiting_read["left"]),
            OlderCount(0),
            now,
            router,
            waiting_read.get("reach"),
            waiting_read,
            pages=pages,
        )
    finally:
        lock.release()


# ---- the full read a first sign-in asks about ----------------------------------------------------------------------


@dataclass
class FullReadOption:
    """One reach the person can choose for reading mail in full: how many days back from today, what that takes in and
    about what it costs."""

    days: int
    count: int = 0
    estimate_usd: float | None = None
    estimate_max_usd: float | None = None
    unpriced: int = 0
    reaches: bool = True
    capped: bool = False
    estimate: bool = False
    unknown: bool = False  # the service could not say how many there are: no number, and the read goes on all the same


def full_read_pending(store: Any, cfg: Any, source: Any) -> bool:
    """Whether a source's first sign-in still has its full-read question open: its first read took mail in, it can be
    asked for older mail, no answer was given (not even "not now") and the workspace offers reaches. A source whose
    first read was made before the question existed is never asked."""
    run = intake_run(store.read(), source.id)
    return bool(
        run is not None
        and run.data.get("asks_full_read")
        and cfg.watch.full_read_choices
        and run.data.get("full_read") is None
        and not run.data.get("older_read")
        and can_look_back(source, store)
    )


#: The answers given to the full-read question before a source's first read, kept on this computer until that read
#: lands and they are recorded with it: the source's id and the reach in days (0 for "not now").
AHEAD = "full-read-ahead.json"


def answers_ahead(ws: Any) -> dict[str, int]:
    """The answers kept for sources whose first read is still to come."""
    try:
        kept = json.loads((ws.private_dir / AHEAD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): int(v) for k, v in kept.items()} if isinstance(kept, dict) else {}


def _keep_ahead(ws: Any, source_id: str, reach: int | None) -> None:
    """Keep a source's answer until its first read (`reach` None drops it). The file is read again under its lock, so
    answers given at the same moment each stay."""
    from engine.state_file import changing, write_whole

    path = ws.private_dir / AHEAD
    with changing(path):
        kept = answers_ahead(ws)
        if reach is None:
            if kept.pop(source_id, None) is None:
                return
        else:
            kept[source_id] = reach
        write_whole(path, json.dumps(kept, sort_keys=True))


def first_read_to_come(store: Any, source: Any) -> bool:
    """Whether a source's first read, the one that takes its mail in quietly and asks the full-read question, has not
    been made yet: it is on, it is taken in on its first read, and no read of it has worked."""
    from engine import capture

    if not source.enabled or source.first_run != "intake" or source.holds == "absence" or capture.is_capture(source):
        return False
    return not any(
        r.data["outcome"] in ("ok", "baseline") for r in store.read().find("watch_run", {"source": source.id})
    )


def _account_answer(ws: Any, store: Any, cfg: Any, source: Any) -> int | None:
    """The answer the person gave to the full-read question for another source of the same account, recorded with its
    first read or kept ahead of it; the furthest reach when they differ, None when no other source was answered. The
    question is asked once per account, so a source that appears later takes this."""
    if not source.account:
        return None
    view, kept = store.read(), answers_ahead(ws)
    answers = []
    for other in cfg.watch.sources:
        if other.id == source.id or other.account != source.account:
            continue
        run = intake_run(view, other.id)
        if run is not None and isinstance(run.data.get("full_read"), int):
            answers.append(int(run.data["full_read"]))
        elif other.id in kept:
            answers.append(kept[other.id])
    return max(answers) if answers else None


def full_read_ahead(ws: Any, store: Any, cfg: Any, source: Any) -> bool:
    """Whether the full-read question is open for a source ahead of its first read: the question is asked from the
    moment the source exists, never only once its service has answered, so one account's reading never holds back
    another's choice. True until the person answers or the first read lands (then `full_read_pending` says)."""
    return bool(
        cfg.watch.full_read_choices
        and first_read_to_come(store, source)
        and can_look_back(source, store)
        and source.id not in answers_ahead(ws)
        and _account_answer(ws, store, cfg, source) is None  # asked once per account
    )


def full_read_open(ws: Any, store: Any, cfg: Any, source: Any, signed_in: bool = True) -> bool:
    """Whether the full-read question is shown for a source: it is open after its first read (`full_read_pending`) or
    ahead of it (`full_read_ahead`, never for an account that is signed out), and neither the source nor another
    source of its account has an answer that is kept or recorded. An answer waiting to be applied (the first read has
    landed and is still taking its mail in) never shows the question again."""
    if source.id in answers_ahead(ws) or _account_answer(ws, store, cfg, source) is not None:
        return False
    return full_read_pending(store, cfg, source) or (signed_in and full_read_ahead(ws, store, cfg, source))


def _follow_own_answer(
    ws: Any, store: Any, cfg: Any, source: Any, now: datetime, router: Any = None
) -> tuple[bool, LookBack | None]:
    """A source that was answered ahead of its first read takes that answer once the read has landed: it is recorded
    with the read and its older mail queued, as if the person had pressed then. An answer that no longer fits (the
    read took no mail in, the choice is gone) is dropped and the source keeps whatever question it has. Returns whether
    an answer was kept for it, and what applying it did."""
    kept = answers_ahead(ws).get(source.id)
    if kept is None or first_read_to_come(store, source):
        return False, None
    found = None
    try:
        if full_read_pending(store, cfg, source) and (kept == 0 or kept in cfg.watch.full_read_choices):
            found = answer_full_read(ws, store, cfg, source.id, kept, now, router)
    except StoreError:
        # It couldn't be recorded this time (another write got in between): the answer stays kept, the question stays
        # answered on screen, and it is applied after the source's next read.
        log.exception("applying the answer kept for %s failed; it is tried again after its next read", source.id)
        return True, None
    _keep_ahead(ws, source.id, None)
    return True, found


def follow_account_answer(
    ws: Any, store: Any, cfg: Any, source_id: str, now: datetime | None = None, router: Any = None
) -> LookBack | None:
    """A source of an account that is read for the first time after the person answered the full-read question for
    another of its sources (the sent mail follows the inbox, which is read first) takes the same answer: the question is
    asked once per account, so one press covers every source the account reads, whenever each one's first read comes.
    An answer given for the source itself ahead of its first read comes first. Returns what the read did, or None when
    nothing applies (no answer was kept, no sibling answered, the choice is not on offer, or the answer is not one of
    the choices any more)."""
    now = now or datetime.now(UTC)
    source = next((s for s in cfg.watch.sources if s.id == source_id), None)
    if source is None:
        return None
    had, found = _follow_own_answer(ws, store, cfg, source, now, router)
    if had:
        return found
    if not source.account or not full_read_pending(store, cfg, source):
        return None
    reach = _account_answer(ws, store, cfg, source)
    if reach is None:
        return None
    if reach and reach not in cfg.watch.full_read_choices:
        return None
    try:
        return answer_full_read(ws, store, cfg, source.id, reach, now, router)
    except StoreError:
        return None


def _days_beyond_first_read(store: Any, source_id: str, reach: int, now: datetime) -> int:
    """How many days further back than the first read a reach of `reach` days from today goes; 0 or less when the first
    read already covers it."""
    old = back_to_of(store.read(), source_id)
    if old is None:
        raise StoreError("this source was not taken in with a look back, so there is nothing further to look at")
    return (old - (now.astimezone(UTC).date() - timedelta(days=reach))).days


_KEPT_COUNTS: dict[tuple[str, str, int, str], tuple[datetime, FullReadOption]] = {}
_KEPT_LOCK = threading.Lock()


def forget_full_read_counts(ws: Any, source_id: str) -> None:
    """Drop what is kept of a source's counts for the full-read choices (it was read, its full read starts or carries
    on, or the next ask must be fresh)."""
    root = str(ws.root)
    with _KEPT_LOCK:
        for key in [k for k in _KEPT_COUNTS if k[0] == root and k[1] == source_id]:
            del _KEPT_COUNTS[key]


def _kept_count(ws: Any, cfg: Any, source_id: str, beyond: int) -> int | None:
    """What the service said it holds for a reach, as the choice showed it (kept for a few minutes); None when no count
    is kept. Never asks the service."""
    key = (str(ws.root), source_id, beyond, f"{repr(_source(cfg, source_id).settings)}|{cfg.watch.full_read_max_items}")
    with _KEPT_LOCK:
        kept = _KEPT_COUNTS.get(key)
    return kept[1].count if kept is not None and not kept[1].unknown and kept[1].count > 0 else None


def full_read_options(
    ws: Any, store: Any, cfg: Any, source_id: str, now: datetime | None = None, router: Any = None
) -> list[FullReadOption]:
    """The reaches offered, each with its count and cost through the look further back's own preview. Nothing is
    chosen and nothing is written. The service is asked once per reach and the answer is kept in memory for
    `watch.full_read_count_minutes` (never stored: it is not knowledge), keyed by the source, its settings and the
    range; a source read, its full read starting or carrying on, or its settings changing drops it."""
    now = now or datetime.now(UTC)
    keep = timedelta(minutes=cfg.watch.full_read_count_minutes)
    source = _source(cfg, source_id)
    if intake_run(store.read(), source_id) is None and first_read_to_come(store, source):
        # Ahead of the first read nothing says where older mail begins, so the service is not asked: every reach is
        # offered with no number, and the counts come once the read has landed.
        return [FullReadOption(reach, unknown=True) for reach in cfg.watch.full_read_choices]
    settings = repr(source.settings)
    found = []
    blind = False
    for reach in cfg.watch.full_read_choices:
        beyond = _days_beyond_first_read(store, source_id, reach, now)
        if beyond < 1:
            found.append(FullReadOption(reach))  # the first read already covers it: nothing more to take in
            continue
        if blind:
            # The service could not say for an earlier reach: it is not asked again for each of the rest.
            found.append(FullReadOption(reach, unknown=True))
            continue
        key = (str(ws.root), source_id, beyond, f"{settings}|{cfg.watch.full_read_max_items}")
        with _KEPT_LOCK:
            kept = _KEPT_COUNTS.get(key)
        if kept is not None and keep > timedelta(0) and timedelta(0) <= now - kept[0] < keep:
            found.append(replace(kept[1], days=reach))
            continue
        preview = look_back_preview(ws, store, cfg, source_id, beyond, now, exact=True, router=router)
        option = FullReadOption(
            reach,
            preview.count,
            preview.estimate_usd,
            preview.estimate_max_usd,
            preview.unpriced,
            preview.reaches,
            preview.capped,
            preview.estimate,
            preview.unknown,
        )
        if preview.unknown:
            blind = True  # not kept: the next ask may get a count
        else:
            with _KEPT_LOCK:
                _KEPT_COUNTS[key] = (now, option)
        found.append(option)
    return _with_first_window(ws, store, cfg, source_id, found, router)


def _with_first_window(
    ws: Any, store: Any, cfg: Any, source_id: str, options: list[FullReadOption], router: Any = None
) -> list[FullReadOption]:
    """The choices with what the source's first window still holds for the go added to each reach's cost: choosing a
    reach is also the go for that window, so the one figure shown is both amounts together. A reach with no number
    (nothing more to read, or the service couldn't say) shows no cost and is left as it is."""
    held = waiting_cost(ws, store, cfg, source_id, router)
    if not held.count:
        return options

    def both(a: float | None, b: float | None) -> float | None:
        return None if a is None and b is None else round((a or 0.0) + (b or 0.0), 4)

    return [
        replace(
            o,
            estimate_usd=both(o.estimate_usd, held.likely),
            estimate_max_usd=both(
                o.estimate_max_usd if o.estimate_max_usd is not None else o.estimate_usd, held.at_most
            ),
            unpriced=o.unpriced + held.unpriced,
        )
        if o.count > 0 and not o.unknown
        else o
        for o in options
    ]


def _record_full_read(store: Any, source_id: str, reach: int | None) -> None:
    run = intake_run(store.read(), source_id)
    if run is None:
        raise StoreError("this source was not taken in with a look back, so there is nothing further to look at")
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        tx.update("watch_run", run.id, {"full_read": reach}, _MOVED, read_version=current.version)


def older_failure(err: Any) -> str:
    """What the person reads when older mail couldn't be read: plain words for the kind of failure, never the service's
    own text."""
    from engine.net import AnswerTooLarge
    from engine.sides import word

    key = "full_read.failed.too_large" if isinstance(err, AnswerTooLarge) else f"full_read.failed.{err.kind}"
    try:
        return word(None, key)
    except KeyError:
        return word(None, "full_read.failed.outage")


def answer_full_read(
    ws: Any,
    store: Any,
    cfg: Any,
    source_id: str,
    reach: int,
    now: datetime | None = None,
    router: Any = None,
    go: bool = True,
) -> LookBack | None:
    """The person's answer to the full-read question: 0 is "not now" (nothing is read, it isn't asked again for this
    sign-in, and no go is given: what the first window holds keeps its own ask); a reach is recorded and queued for the
    worker's lane, which reads it in the background in slices, so the answer returns at once and never waits for the
    service (no count is asked, no page read). A reach is the one ask for the source's reading, so it is also the go
    (`go`; False keeps the work held, as a look further back does): what the first window holds is queued now, and
    what the read of older mail takes in is queued as it comes, with no second ask. The budgets and each run's own
    limits still hold when the worker runs them. Returns the queued read (`stopped` is "queued"), or None for "not
    now" or a reach the first read already covers."""
    now = now or datetime.now(UTC)
    source = _source(cfg, source_id)
    if intake_run(store.read(), source_id) is None and first_read_to_come(store, source):
        return _answer_ahead(ws, store, cfg, source, reach, now, router)
    if reach == 0:
        _record_full_read(store, source_id, 0)
        return None
    if reach not in cfg.watch.full_read_choices:
        raise StoreError(f"{reach} days is not one of the choices")
    beyond = _days_beyond_first_read(store, source_id, reach, now)
    if beyond < 1:
        _record_full_read(store, source_id, reach)
        if go:
            grant_go(ws, store, cfg, source_id, router, now)
        return None
    if not can_look_back(source, store):
        raise StoreError("this source can't be asked for older mail")
    asked, old, _new, available = _plan(store, cfg, source_id, beyond, exact=True)
    since, before = _remote_range(store, source_id, asked, old, available)
    run = intake_run(store.read(), source_id)
    about = _kept_count(ws, cfg, source_id, beyond)
    queued = {
        **({"about": about} if about else {}),
        "since": since.isoformat(),
        "before": before.isoformat(),
        "left": cfg.watch.full_read_max_items,
        "kind": "queued",
        "stopped_at": now.isoformat(),
        "tries": 0,
        "taken": 0,
        "reach": reach,
        "at": now.isoformat(),
        "gave_up": False,
        **({"go": True} if go else {}),
    }
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        changes: dict[str, Any] = {"full_read": reach}
        if not current.data.get("older_read"):
            changes["older_read"] = queued
        elif go and not current.data["older_read"].get("go"):
            # A read already under way keeps its place; the person's go now covers it too, so the slices it brings later
            # never wait for a go the person already gave.
            changes["older_read"] = {**current.data["older_read"], "go": True}
        tx.update("watch_run", run.id, changes, _MOVED, read_version=current.version)
    forget_full_read_counts(ws, source_id)
    if go:
        grant_go(ws, store, cfg, source_id, router, now)
    result = LookBack(days=beyond, from_date=asked, reaches=True)
    result.stopped, result.continues_at = "queued", now.isoformat()
    return result


def _answer_ahead(
    ws: Any, store: Any, cfg: Any, source: Any, reach: int, now: datetime, router: Any = None
) -> LookBack | None:
    """An answer given before the source's first read: nothing is read and nothing is asked of the service. The answer
    is kept and takes effect when the first read lands (`follow_account_answer`, after every read), the go with it.
    Returns the read still to come (`stopped` is "first_look"), or None for "not now"."""
    if reach and reach not in cfg.watch.full_read_choices:
        raise StoreError(f"{reach} days is not one of the choices")
    if not can_look_back(source, store):
        raise StoreError("this source can't be asked for older mail")
    _keep_ahead(ws, source.id, reach)
    if not first_read_to_come(store, source):
        # The first read landed while the answer was being kept: it is applied now rather than at the next read.
        return _follow_own_answer(ws, store, cfg, source, now, router)[1]
    if reach == 0:
        return None
    result = LookBack(days=reach, from_date=now.astimezone(UTC).date() - timedelta(days=reach), reaches=True)
    result.stopped = "first_look"
    return result


def resume_older_read(store: Any, source_id: str, now: datetime | None = None) -> bool:
    """The person asked to carry on a read of older mail that gave up: it is due at once with a new round of tries, and
    the worker's lane reads it. Returns whether one was waiting."""
    now = now or datetime.now(UTC)
    waiting_read = older_read_waiting(store.read(), source_id)
    run = intake_run(store.read(), source_id)
    if waiting_read is None or run is None:
        return False
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        kept = dict(current.data.get("older_read") or {})
        kept.update(tries=0, gave_up=False, at=now.isoformat())
        tx.update("watch_run", run.id, {"older_read": kept}, _MOVED, read_version=current.version)
    return True


def read_full_now(
    ws: Any, store: Any, cfg: Any, source_id: str, reach: int, now: datetime | None = None, router: Any = None
) -> LookBack | None:
    """`answer_full_read` that also reads the whole reach before returning, in this thread, through the look further
    back. The product never calls it (a press is answered by the lane); it is for tests of what a read does."""
    now = now or datetime.now(UTC)
    source = _source(cfg, source_id)
    if reach == 0:
        _record_full_read(store, source_id, 0)
        return None
    if reach not in cfg.watch.full_read_choices:
        raise StoreError(f"{reach} days is not one of the choices")
    beyond = _days_beyond_first_read(store, source_id, reach, now)
    # The choice is recorded before the read starts, so a read that stops partway never asks the question again.
    _record_full_read(store, source_id, reach)
    if beyond < 1:
        return None
    try:
        return look_further_back(ws, store, cfg, source.id, beyond, now, router, exact=True, reach_days=reach)
    except StoreError:
        _record_full_read(store, source_id, None)  # nothing was read: the question stays open for another try
        raise
