"""Areas of the person's life offered by the assistant (design 6.32, "Personal life").

Items filed under the personal project are narrowed by a plain rule (`areas.narrowed`: those that share a whole word
with enough others). Whether they make an area of the person's life is the assistant's judgment: one request of the
`area-read` kind, estimated first and held for the person's go above the configured amount like any other run, made when
items it has not been asked about have arrived. It reads what the items are about, never who sent them: an area is named
for its subject ("Book collecting" for book orders from two shops), gathers the deliveries, cases and follow-ups about
it whichever shop or sender they came from, and says why. A shop, a service, a sender or a person is never an area by
itself.

Its answer is one `area.offer` op: an offer record for each area, which waits for the person. The applier's checks are
exact: every item is one the packet listed (of the kind it names), an item is in one offer at most, an area has at
least two items, its name is not already a project's or a person's, a team's or an organization's, and no two offers
share a name. Nothing is moved until the person keeps an offer (`areas.keep`, their own edit with Undo).

With no account that can do the work, or a run the person declined, nothing is offered.

Nothing here reaches a service.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from engine import areas, sides
from engine.storage import WriteContext
from engine.untrusted import neutralize

TASK = "area-read"
_ENGINE = WriteContext(actor="engine", trust="trusted", op="area_offers.queue")
#: The request states in which the assistant still has the reading, or the person has to act before it can go on.
IN_HAND = ("queued", "running", "needs_you")
#: How the candidate items and the person's existing areas are marked in the packet.
ITEMS_BLOCK = "area-items"
#: The most items one reading is asked about, newest first.
MOST_ITEMS = 60
#: An area has at least this many items.
LEAST_ITEMS = 2
_KIND_WORDS = {"action": "to-do", "question": "question", "fact": "fact", "event": "calendar entry"}


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def _asked(view: Any) -> set[str]:
    """The ids of the items any reading has been asked about, whatever became of it."""
    found: set[str] = set()
    for r in view.list("request"):
        if r.data["task"] == TASK and not r.data.get("dismissed"):
            found.update(r.data.get("asked_about") or [])
    return found


def candidates(store: Any, cfg: Any) -> list[areas.Candidate]:
    """The items to ask about: the narrowed ones, newest first, at most `MOST_ITEMS`."""
    return areas.narrowed(store.read(), cfg)[:MOST_ITEMS]


# ---- the checks ------------------------------------------------------------------------------------------------------


def _taken_names(view: Any) -> set[str]:
    """The names that already belong to a project, a person, a team or an organization, in lower case."""
    names: set[str] = set()
    for kind, field in (
        ("project", "name"),
        ("person", "full_name"),
        ("team", "name"),
        ("organization", "name"),
    ):
        names |= {str(r.data.get(field) or "").strip().lower() for r in view.list(kind)}
    names |= {
        str(r.data.get("name") or "").strip().lower()
        for r in view.list("area_offer")
        if r.data["status"] != "dismissed"
    }
    names.discard("")
    return names


def problems(view: Any, listed: dict[str, str], areas_given: list[Any]) -> list[str]:
    """What is wrong with an offer's areas, in plain words, or nothing. `listed` is the packet's items, by id to
    kind."""
    said: list[str] = []
    taken = _taken_names(view)
    named: set[str] = set()
    used: set[str] = set()
    for area in areas_given:
        name = " ".join(area.name.split())
        key = name.lower()
        if key in taken:
            said.append(
                f"'{name}' is already the name of a project, a person, a team or an organization; "
                "name the area for what its items are about"
            )
        if key in named:
            said.append(f"two areas are called '{name}'; give each its own name")
        named.add(key)
        if len(area.items) < LEAST_ITEMS:
            said.append(f"'{name}' has fewer than {LEAST_ITEMS} items, which is not an area of life")
        for item in area.items:
            if item.id not in listed:
                said.append(f"{item.id} is not an item the list holds")
            elif listed[item.id] != item.kind:
                said.append(f"{item.id} is a {_KIND_WORDS[listed[item.id]]}, not a {_KIND_WORDS[item.kind]}")
            elif item.id in used:
                said.append(f"{item.id} is in more than one area; give each item one area")
            used.add(item.id)
    return said


def check(ctx: Any, op: Any) -> list[str]:
    """The problems with an `area.offer` op as the applier sees it: its items are those the request's packet listed."""
    request = ctx.store.read().get("request", ctx.inputs.request) if ctx.inputs.request else None
    asked = (request.data.get("asked_about") if request is not None else None) or []
    view = ctx.store.read()
    listed = {}
    for item_id in asked:
        for kind in ("action", "question", "fact", "event"):
            if view.get(kind, item_id) is not None:
                listed[item_id] = kind
                break
    return problems(view, listed, list(op.areas))


def apply(tx: Any, op: Any, ctx: Any, w: Any) -> list[dict[str, Any]]:
    """Keep each area as an offer that waits for the person: its name, why and its items, as of now."""
    made = []
    now = ctx.store.clock()
    for area in op.areas:
        offer = tx.create(
            "area_offer",
            {
                "name": " ".join(neutralize(area.name).split())[:60],
                "why": " ".join(neutralize(area.why).split())[:240],
                "items": [{"kind": i.kind, "id": i.id} for i in area.items],
                "status": "offered",
                "offered_at": now,
            },
            w,
        )
        made.append({"kind": "area_offer", "id": offer.id})
    return made


# ---- asking for it ---------------------------------------------------------------------------------------------------


def _requests(view: Any, personal: str) -> list[Any]:
    return [
        r
        for r in view.list("request")
        if r.data["task"] == TASK and (r.data.get("about") or {}).get("id") == personal and not r.data.get("dismissed")
    ]


def due(store: Any, cfg: Any) -> bool:
    """Whether a reading is due: the person is set, there is a personal project, nothing is in hand, and some item the
    rule narrowed to has not been asked about yet (a try that failed or was declined is not asked again by itself, until
    new items arrive)."""
    from engine.dispatcher import person_is_set

    view = store.read()
    personal = sides.personal_project(view, cfg)
    if personal is None or not person_is_set(store, cfg):
        return False
    if any(r.data["state"] in IN_HAND for r in _requests(view, personal)):
        return False
    return any(c.id not in _asked(view) for c in candidates(store, cfg))


def queue(store: Any, cfg: Any, now: datetime) -> str | None:
    """Queue a reading when one is due, as a scheduled request that remembers the items it asks about. It then goes
    through the request path: its estimate, the person's go above the configured amount, its budget. Returns its id, or
    None."""
    if not due(store, cfg):
        return None
    personal = sides.personal_project(store.read(), cfg)
    ids = [c.id for c in candidates(store, cfg)]
    with store.transaction() as tx:
        if any(r.data["state"] in IN_HAND for r in _requests(tx, personal)):
            return None
        made = tx.create(
            "request",
            {
                "task": TASK,
                "about": {"kind": "project", "id": personal},
                "origin": "schedule",
                "state": "queued",
                "waiting": "With the assistant, starting now",
                "asked_about": ids,
                "created_at": now.isoformat(),
            },
            _ENGINE,
        )
    return made.id


def skip_reason(store: Any, cfg: Any, request: Any) -> str | None:
    """Why a reading has nothing to do any more, in plain words, or None: there is no personal project, or none of the
    items it was asked about is still among the narrowed ones. Decided before any packet, estimate or call."""
    view = store.read()
    if sides.personal_project(view, cfg) is None:
        return "There is no personal project to read."
    wanted = set(request.get("asked_about") or [])
    if not any(c.id in wanted for c in candidates(store, cfg)):
        return "There is nothing left to read."
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
    """A reading was applied: the offers show on Today, so the run needs no review of its own and is done."""
    with store.transaction() as tx:
        found = tx.get("changeset", changeset_id)
        current = tx.get("request", request_id)
        if found is None or current is None or any(o["status"] == "held" for o in found.data["ops"]):
            return
        tx.update("request", request_id, {"state": "done", "waiting": None}, _ENGINE, read_version=current.version)


# ---- the packet ------------------------------------------------------------------------------------------------------


def _line(view: Any, item: areas.Candidate) -> str:
    bits = [f"[{item.id}] {_KIND_WORDS[item.kind]}", _one_line(item.text)]
    record = view.get(item.kind, item.id)
    if item.kind == "event" and record is not None:
        bits.insert(1, str(record.data["start"])[:10])
        delivery = record.data.get("delivery")
        if delivery:
            kept = {
                k: v for k, v in delivery.items() if k not in ("tracking", "order", "dated") and v not in (None, "")
            }
            if kept:
                bits.append("delivery " + ", ".join(f"{k}: {_one_line(v)}" for k, v in kept.items()))
    bits.append("shares: " + ", ".join(item.shared))
    return " | ".join(bits)


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date) -> Any:
    """The packet for one reading. Stable first: the instructions, the op reference, the practice, what has been learned
    and the people on file. Then the request: the items the rule narrowed to, marked as from outside, and the areas and
    projects the person already has."""
    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.names import PacketPeople
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _people, _task
    from engine.prompts import render

    view = store.read()
    personal = sides.personal_project(view, cfg)
    if personal is None:
        raise PacketRefused("there is no personal project to read")
    wanted = set(req.data.get("asked_about") or [])
    found = [c for c in candidates(store, cfg) if c.id in wanted]
    if not found:
        raise PacketRefused("there is nothing left to read")
    shown = neutralize("\n".join(_line(view, c) for c in found))
    have = sorted(
        {
            str(p.data["name"])
            for p in view.list("project")
            if p.id != personal and p.id in areas._inside(view, personal)
        },
        key=str.lower,
    )
    waiting = sorted(
        {
            str(o.data["name"])
            for o in view.list("area_offer")
            if o.data["status"] == "offered" and str(o.data.get("name") or "").strip()
        },
        key=str.lower,
    )
    people = PacketPeople(store, cfg)
    learned = _learned(store, cfg, kind, people, projects=[], source=None, text=shown, today=today)
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
        learned.per_input,
        "# Areas and projects the person has kept (an item about a narrower kind of one of these belongs inside it: "
        "leave it out, and offer no area for it)\n"
        + ("\n".join(f"- {neutralize(n)}" for n in have) if have else "(none)"),
        "# Areas already offered and waiting for the person (the same applies: offer nothing that overlaps one)\n"
        + ("\n".join(f"- {neutralize(n)}" for n in waiting) if waiting else "(none)"),
        f'# Items filed under Personal\n<untrusted source="{ITEMS_BLOCK}">\n{shown}\n</untrusted>',
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
        cites=f"project:{personal}",
        about=("project", personal),
        data_level=_data_level(store, req.data),
        knowledge=learned.log,
    )
