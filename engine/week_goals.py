"""The goals offered for the week (design 6.32, the Monday briefing): the assistant's reading of what matters most in
the coming week.

What the week holds is gathered from the records by plain functions (`narrowed`): the person's own open to-dos due
through the week (late ones too), the promises others made to them that fall due in it, the week's calendar, and the
goals the person confirmed in earlier weeks. A plain function only narrows what the assistant looks at. Which of it
matters most, and in what words, is the assistant's judgment: one request of the `monday-goals` kind, estimated first
and held for the person's go above the configured amount like any other run, made once for a week and again only when
the person asks. Its answer is one `week.goals` op, kept on the person's `week_plan` record for the week as an offer,
and the applier's checks are exact: every goal that names a record names one the packet listed, no record and no words
twice, none when nothing is due, and at most `steward.brief.goals_max`.

The offer is never a confirmed goal. The person confirms, changes or drops it as they do any goals
(`engine/week_plan.py`). With no account that can do the work, or a run the person declined, no goals are offered and
the person writes their own.

Nothing here reaches a service.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine import sides, week_ahead, week_plan
from engine.blocked import standing_hold
from engine.firm_due import firm_due
from engine.names import People
from engine.storage import StoreError, WriteContext
from engine.today import zone
from engine.untrusted import neutralize

TASK = "monday-goals"
_QUEUE = WriteContext(actor="pm", trust="trusted", op="week_goals.ask")
_ENGINE = WriteContext(actor="engine", trust="trusted", op="week_goals.queue")
#: The request states in which the assistant still has the offer, or the person has to act before it can go on.
IN_HAND = ("queued", "running", "needs_you")
#: How the week's records and the person's earlier goals are marked in the packet.
ITEMS_BLOCK = "week-items"
KEPT_BLOCK = "goals-kept"
#: How many earlier weeks' confirmed goals the packet shows.
EARLIER_WEEKS = 4


@dataclass(frozen=True)
class Item:
    """One record the assistant may build a goal from: its `id`, what `kind` it is (task, promise or a calendar kind
    from the week ahead), the day it falls on, its words and a short detail. `due` is true for the to-dos and promises
    whose day falls in or before the week: the things that make the week worth a reading."""

    id: str
    kind: str
    day: date | None
    text: str
    detail: str = ""
    due: bool = False


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def _week(cfg: Any, now: datetime) -> tuple[date, date]:
    """The week the person's day `now` belongs to, by the working days: its first and last working day."""
    return week_plan.week_bounds(cfg, now.astimezone(zone(cfg)).date())


def _tasks(store: Any, cfg: Any, last: date) -> list[Item]:
    """The person's own open to-dos due through the week, and the promises others made to them that fall due in it."""
    view = store.read()
    people = People(store, cfg)
    pm = people.pm
    found: list[Item] = []
    for action in view.list("action"):
        d = action.data
        if d.get("status") != "open" or d.get("reply_owed") or standing_hold(view, d, people):
            continue
        day = firm_due(d)
        if day is None or day > last:
            continue
        mine = pm is not None and any(o.get("person") == pm for o in d.get("owners") or [])
        if mine:
            found.append(Item(action.id, "task", day, _one_line(d["text"]), due=True))
        elif pm in (d.get("promised_to") or []):
            owners = ", ".join(people.name(o["person"]) for o in d.get("owners") or [] if o.get("person"))
            found.append(Item(action.id, "promise", day, _one_line(d["text"]), f"promised to you by {owners}", True))
    return found


def narrowed(store: Any, cfg: Any, now: datetime) -> list[Item]:
    """What the assistant is shown for the week: the due to-dos and promises first, then the week's calendar (what
    happens in it, never a to-do twice). Soonest first within each."""
    first, last = _week(cfg, now)
    found = sorted(_tasks(store, cfg, last), key=lambda i: (i.day or last, i.text.lower(), i.id))
    taken = {i.id for i in found}
    calendar = [
        Item(i.id, i.kind, i.first, i.title, i.detail)
        for i in week_ahead.items(store, cfg, now, first, last)
        if i.id not in taken and i.kind != "task"
    ]
    return found + calendar


def due_items(store: Any, cfg: Any, now: datetime) -> list[Item]:
    """The to-dos and promises that make a week worth a reading: with none, nothing is asked and nothing is offered."""
    return [i for i in narrowed(store, cfg, now) if i.due]


def earlier_goals(store: Any, cfg: Any, first: date) -> list[tuple[date, list[str]]]:
    """The goals the person confirmed in the weeks before `first`, the latest weeks first."""
    view = store.read()
    person = People(store, cfg).pm
    found = []
    for plan in view.list("week_plan"):
        week = date.fromisoformat(str(plan.data["week"]))
        if plan.data.get("person") == person and plan.data.get("confirmed_at") and week < first and plan.data["goals"]:
            found.append((week, list(plan.data["goals"])))
    return sorted(found, reverse=True)[:EARLIER_WEEKS]


# ---- the checks ------------------------------------------------------------------------------------------------------


def problems(store: Any, cfg: Any, now: datetime, goals: list[Any]) -> list[str]:
    """What is wrong with an offer's goals, in plain words, or nothing. Exact checks: a goal that names a record names
    one the packet listed, no record and no words twice, nothing is offered when nothing is due, and there are at most
    `steward.brief.goals_max`."""
    listed = {i.id for i in narrowed(store, cfg, now)}
    most = cfg.steward.brief.goals_max
    said: list[str] = []
    cited: set[str] = set()
    worded: set[str] = set()
    if goals and not due_items(store, cfg, now):
        return ["nothing is due in the week, so no goals are offered for it"]
    for goal in goals:
        key = " ".join(goal.words.split()).casefold()
        if key in worded:
            said.append(f"the goal '{goal.words}' is given twice; give each goal once")
        worded.add(key)
        if goal.source is None:
            continue
        if goal.source in cited:
            said.append(f"{goal.source} is the source of more than one goal; give each record one goal")
        cited.add(goal.source)
        if goal.source not in listed:
            said.append(f"{goal.source} is not a record the week's list holds")
    if len(goals) > most:
        said.append(f"give at most {most} goals; this has {len(goals)}")
    return said


def _request_time(request: Any) -> datetime | None:
    return week_ahead._stamp(request.data.get("created_at")) if request is not None else None


def check(ctx: Any, op: Any) -> list[str]:
    """The problems with a `week.goals` op as the applier sees it: it is for the week of the request's `week_plan`, as
    of when the request was made."""
    request = ctx.store.read().get("request", ctx.inputs.request) if ctx.inputs.request else None
    about = (request.data.get("about") or {}) if request is not None else {}
    plan = ctx.store.read().get("week_plan", about.get("id")) if about.get("kind") == "week_plan" else None
    if plan is None:
        return ["goals are offered for a week the person has a record for"]
    return problems(ctx.store, ctx.cfg, _request_time(request) or datetime.now(UTC), list(op.goals))


def apply(tx: Any, op: Any, ctx: Any, w: Any) -> list[dict[str, Any]]:
    """Keep an offer on the person's record for the week the request is for: its goals (each with the record it comes
    from, when it names one) and when it was made. The person's confirmed goals are never touched."""
    request = tx.get("request", ctx.inputs.request) if ctx.inputs.request else None
    about = (request.data.get("about") or {}) if request is not None else {}
    plan = tx.get("week_plan", about["id"]) if about.get("kind") == "week_plan" else None
    if plan is None:
        raise StoreError("the week this offer was for is gone")
    offer = [{"words": _one_line(neutralize(g.words))[: week_plan.GOAL_LIMIT], "source": g.source} for g in op.goals]
    tx.update(
        "week_plan",
        plan.id,
        {"goals_offer": offer, "goals_offered_at": ctx.store.clock()},
        w,
        read_version=plan.version,
    )
    return [{"kind": "week_plan", "id": plan.id}]


# ---- asking for it ---------------------------------------------------------------------------------------------------


def _requests(view: Any, plan_id: str) -> list[Any]:
    return [
        r
        for r in view.list("request")
        if r.data["task"] == TASK and (r.data.get("about") or {}).get("id") == plan_id and not r.data.get("dismissed")
    ]


def _plan_id(store: Any, cfg: Any, now: datetime) -> str | None:
    first, _ = _week(cfg, now)
    found = week_plan.plan_of(store.read(), People(store, cfg).pm, first)
    return found.id if found is not None else None


def make_request(store: Any, cfg: Any, now: datetime, origin: str) -> str:
    """Queue an offer for the week `now` falls in, with no check that one is due: the request path closes it with no
    call when nothing is due. Returns the request. Refused while the assistant has one in hand or the goals are
    confirmed."""
    context = _QUEUE if origin == "pm" else _ENGINE
    person = People(store, cfg).pm
    first, _ = _week(cfg, now)
    with store.transaction() as tx:
        found = week_plan.plan_of(tx, person, first)
        plan_id = (
            found.id
            if found is not None
            else tx.create("week_plan", {"person": person, "week": first.isoformat()}, context).id
        )
        if any(r.data["state"] in IN_HAND for r in _requests(tx, plan_id)):
            raise StoreError("The assistant already has this week's goals in hand.")
        if week_plan.goals_of(tx, person, first):
            raise StoreError("This week's goals are already confirmed.")
        made = tx.create(
            "request",
            {
                "task": TASK,
                "about": {"kind": "week_plan", "id": plan_id},
                "origin": origin,
                "state": "queued",
                "waiting": "With the assistant, starting now",
                "created_at": now.isoformat(),
            },
            context,
        )
    return made.id


def ask(store: Any, cfg: Any, now: datetime) -> str:
    """The person's "Offer goals": queue an offer for this week, estimated first and held for their go above the
    configured amount. Returns the request. Refused while the assistant has one in hand, once the goals are confirmed
    and when nothing is due."""
    if not due_items(store, cfg, now):
        raise StoreError("Nothing is due this week, so there is nothing to offer goals from.")
    return make_request(store, cfg, now, "pm")


def due(store: Any, cfg: Any, now: datetime) -> bool:
    """Whether this week's first offer is due: the person is set, the Monday briefing is the form to show (so the goals
    are not confirmed and the offer is not dismissed), nothing has been asked for the week yet (a try that failed or was
    declined is not asked again by itself) and something is due in it."""
    from engine import brief
    from engine.dispatcher import person_is_set

    if not person_is_set(store, cfg):
        return False
    person = People(store, cfg).pm
    first, _ = _week(cfg, now)
    view = store.read()
    confirmed = bool(week_plan.goals_of(view, person, first))
    if confirmed or "monday" not in brief.available(
        cfg, now, confirmed, week_plan.offer_dismissed(view, person, first)
    ):
        return False
    plan_id = _plan_id(store, cfg, now)
    if plan_id is not None and _requests(view, plan_id):
        return False
    return bool(due_items(store, cfg, now))


def queue(store: Any, cfg: Any, now: datetime) -> str | None:
    """Queue the week's first offer when it is due, as a scheduled request. It then goes through the request path: its
    estimate, the person's go above the configured amount, its budget. Returns its id, or None."""
    if not due(store, cfg, now):
        return None
    return make_request(store, cfg, now, "schedule")


def skip_reason(store: Any, cfg: Any, request: Any, now: datetime) -> str | None:
    """Why an offer has nothing to do any more, in plain words, or None: the week it was for is gone, the person
    confirmed their goals meanwhile, or nothing is due in it any more. Decided before any packet, estimate or call."""
    about = request.get("about") or {}
    plan = store.read().get("week_plan", about.get("id"))
    if plan is None:
        return "The week this offer was for is gone."
    if plan.data.get("confirmed_at") and plan.data.get("goals"):
        return "You have already set this week's goals."
    if not due_items(store, cfg, now):
        return "Nothing is due this week."
    return None


def close(store: Any, request_id: str, why: str) -> None:
    with store.transaction() as tx:
        current = tx.get("request", request_id)
        if current is not None and (current.data["state"], current.data.get("waiting")) != ("done", why):
            tx.update(
                "request",
                request_id,
                {"state": "done", "waiting": why, "cause": None},
                _ENGINE,
                read_version=current.version,
            )


def finish(store: Any, request_id: str, changeset_id: str) -> None:
    """An offer was applied: the briefing shows it, so the run needs no review of its own and is done."""
    with store.transaction() as tx:
        found = tx.get("changeset", changeset_id)
        current = tx.get("request", request_id)
        if found is None or current is None or any(o["status"] == "held" for o in found.data["ops"]):
            return
        tx.update("request", request_id, {"state": "done", "waiting": None}, _ENGINE, read_version=current.version)


# ---- the packet ------------------------------------------------------------------------------------------------------


def _line(item: Item) -> str:
    bits = [f"[{item.id}] {item.kind}", item.day.isoformat() if item.day else "no day", item.text]
    if item.detail:
        bits.append(item.detail)
    return " | ".join(bits)


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date) -> Any:
    """The packet for one offer. Stable first: the instructions, the op reference, the practice, what has been learned
    and the people on file. Then the request: the week's days, the most goals, the week's records and the goals the
    person kept before. The records are marked as from outside."""
    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.names import PacketPeople
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _people, _task
    from engine.prompts import render

    about = req.data.get("about") or {}
    plan = store.read().get("week_plan", about.get("id")) if about.get("kind") == "week_plan" else None
    if plan is None:
        raise PacketRefused("the week this offer was for is gone")
    moment = week_ahead._stamp(req.data.get("created_at")) or (
        datetime.combine(today, datetime.min.time(), tzinfo=zone(cfg)) + timedelta(hours=12)
    )
    first, last = _week(cfg, moment)
    found = narrowed(store, cfg, moment)
    if not any(i.due for i in found):
        raise PacketRefused("nothing is due in the week to offer goals from")
    shown_items = neutralize("\n".join(_line(i) for i in found))
    before = earlier_goals(store, cfg, first)
    shown_before = neutralize("\n".join(f"week of {week.isoformat()}: " + "; ".join(goals) for week, goals in before))
    people = PacketPeople(store, cfg)
    learned = _learned(
        store, cfg, kind, people, projects=[], source=None, text=f"{shown_items}\n{shown_before}", today=today
    )
    instructions = render(kind.prompt, {"assistant_name": cfg.workspace.assistant_name}, ws.root, kind.prompt_file)
    stable = "\n\n".join(
        part
        for part in (
            "# Op reference\n" + reference_for(list(kind.ops), store.plugins.ops, reach=reach_choices(store.plugins)),
            "# Practice\n" + _guidance(kind),
            learned.stable,
            "# People on file\n" + _people(store, cfg),
        )
        if part.strip()
    )
    parts = [
        f"Today is {today.isoformat()} ({today.strftime('%A')}).",
        f"The week runs from {first.isoformat()} through {last.isoformat()}. "
        f"Give at most {cfg.steward.brief.goals_max} goals.",
        learned.per_input,
        f'# The week\'s records\n<untrusted source="{ITEMS_BLOCK}">\n{shown_items}\n</untrusted>',
        f'# Goals the person kept in earlier weeks\n<untrusted source="{KEPT_BLOCK}">\n{shown_before}\n</untrusted>'
        if shown_before
        else "",
    ]
    request = "\n\n".join(p for p in parts if p)
    task = replace(_task(cfg, store, kind, instructions, stable, request), knowledge=learned.log.model_dump())
    return Packet(
        task,
        request,
        Cleaned("", 0, 0, False, 0),
        "",
        too_long=False,
        untrusted_material=True,
        cites=f"week_plan:{plan.id}",
        about=("week_plan", plan.id),
        data_level=_data_level(store, req.data),
        knowledge=learned.log,
    )


# ---- what the briefing shows -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Offer:
    """The offer as the briefing shows it. `state`: offered (goals wait: `goals` with the side of each, none on a side
    being None), empty (the assistant read the week and offered none), working (queued or running), needs_go (held for
    the person's go, with `estimate_usd` when there is one) or none (nothing asked yet, or it stopped). `can_ask` is
    whether the person may ask for one now."""

    state: str
    goals: tuple[str, ...] = ()
    sides: tuple[str | None, ...] = ()
    estimate_usd: float | None = None
    can_ask: bool = False


def offer_of(store: Any, cfg: Any, now: datetime) -> Offer:
    """The offer for the week `now` falls in. Reads only."""
    view = store.read()
    person = People(store, cfg).pm
    first, _ = _week(cfg, now)
    plan = week_plan.plan_of(view, person, first)
    asked = due_items(store, cfg, now) != []
    if plan is None:
        return Offer("none", can_ask=asked)
    live = None
    for r in sorted(_requests(view, plan.id), key=lambda r: (str(r.data["created_at"]), r.id), reverse=True):
        live = r
        break
    state = live.data["state"] if live is not None else None
    if state in ("queued", "running"):
        return Offer("working")
    if state == "needs_you" and live.data.get("approval") == "required":
        return Offer("needs_go", estimate_usd=live.data.get("estimate_usd"))
    if plan.data.get("goals_offered_at"):
        goals = plan.data.get("goals_offer") or []
        found = tuple(g["words"] for g in goals)
        where = tuple(
            sides.side_of_item(view, cfg, rec)
            if (rec := view.get("action", g["source"]) if g.get("source") else None)
            else None
            for g in goals
        )
        return Offer("offered" if found else "empty", found, where, can_ask=asked)
    return Offer("none", can_ask=asked)
