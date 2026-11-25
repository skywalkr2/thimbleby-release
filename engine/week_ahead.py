"""The week ahead (design 6.32, the Monday briefing and the Schedule): the assistant's reading of the coming week. One
sentence on what kind of week it is and one row for each thing that happens in it, each row naming the day or window it
falls on, a few words, and the record it comes from.

The week's things are gathered from the records by plain functions (`items`): deliveries by when they arrive, to-dos and
dated facts with a day in the week, windows and meetings on the calendar, and kept routines the person's days away pause
or let start again. Which of them matter, and what to say about them, is the assistant's judgment: one request of the
`week-ahead` kind, estimated first and held for the person's go above the configured amount like any other run, made
once a week and again only when the person asks. Its answer is one `week.read` op, kept on the person's `week_plan`
record for the week, and the applier's checks are exact: every row cites a record that exists and falls in the week,
each record has one row, nothing Today already holds a line for is repeated, and there are at most
`steward.week_ahead.max_rows` rows.

With no account that can do the work, or a run the person declined, the rows are built by rules from the same records,
with no sentence and the same row limit. The person's "Not this week" sets one record aside for the week and records a
signal.

Nothing here reaches a service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine import routines, sides, week_plan
from engine.blocked import standing_hold
from engine.facts import superseded_by
from engine.firm_due import firm_due
from engine.local_day import day_of
from engine.names import People
from engine.storage import StoreError, WriteContext
from engine.today import zone
from engine.untrusted import neutralize

TASK = "week-ahead"
_QUEUE = WriteContext(actor="pm", trust="trusted", op="week_ahead.read")
_ENGINE = WriteContext(actor="engine", trust="trusted", op="week_ahead.queue")
_SET_ASIDE = WriteContext(actor="pm", trust="trusted", op="week_ahead.set_aside")
#: The request states in which the assistant still has the reading, or the person has to act before it can go on.
IN_HAND = ("queued", "running", "needs_you")
#: How the week's records and Today's lines are marked in the packet, so a model quotes ids whole.
WEEK_BLOCK = "week-records"
TODAY_BLOCK = "today-lines"
#: What a row of each kind comes first by, when two fall on one day.
_ORDER = ("deadline", "task", "delivery", "meeting", "window", "routine", "entry")


@dataclass(frozen=True)
class Item:
    """One thing in the week the assistant may give a row: the record `id` it comes from, what `kind` of thing it is,
    the first and last day it falls on, its title and a short plain detail (never a tracking number)."""

    id: str
    kind: str
    first: date
    last: date | None
    title: str
    detail: str = ""
    untrusted: bool = True


#: A day written as year-month-day numbers.
_ISO_DAY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def week_of(cfg: Any, today: date) -> tuple[date, date]:
    """The seven days the week `today` belongs to runs: from the week's first working day through six days later, so
    the weekend is in it (the Monday briefing's week)."""
    first, _ = week_plan.week_bounds(cfg, today)
    return first, first + timedelta(days=6)


def ahead(cfg: Any, today: date) -> tuple[date, date]:
    """The days the week ahead covers: from tomorrow (today is Today's) through the last day of the week `today` belongs
    to. Past the week's last day there are none, and `start` is after `last`."""
    first, last = week_of(cfg, today)
    return max(first, today + timedelta(days=1)), last


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def _day(value: Any) -> date | None:
    try:
        return day_of(value, UTC)
    except ValueError:
        return None


# ---- what Today holds ------------------------------------------------------------------------------------------------


def _today_lines(ws: Any, store: Any, cfg: Any, now: datetime) -> list[Any]:
    from engine.today_queue import queue_split

    return list(queue_split(ws, store, cfg, now).shown)


def _ids_of(line: Any) -> set[str]:
    """The ids of the records one Today line stands for."""
    ids: set[str] = set(line.actions) | set(line.questions)
    for name in ("question", "fact", "event", "entry", "other_entry"):
        value = getattr(line, name, None)
        if value:
            ids.add(str(value))
    ids.update(str(i["id"]) for i in line.due_items if i.get("id"))
    return ids


def on_today(ws: Any, store: Any, cfg: Any, now: datetime) -> set[str]:
    """The ids of the records Today already holds a line for."""
    found: set[str] = set()
    for line in _today_lines(ws, store, cfg, now):
        found |= _ids_of(line)
    return found


# ---- the week's records ----------------------------------------------------------------------------------------------


def _agenda_items(store: Any, cfg: Any, now: datetime, first: date, last: date) -> list[Item]:
    from engine.today import agenda

    view = store.read()
    found: list[Item] = []
    seen: set[str] = set()
    for a in agenda(store, cfg, now, through=last, start=first):
        record = view.get("event", a.snapshot) if a.own else view.get("snapshot", a.snapshot)
        if record is None or a.cancelled or a.held or not a.days or a.snapshot in seen:
            continue
        d = record.data
        if a.own and (d.get("reminder") or d.get("role") == "brief_only" or d.get("series")):
            continue  # the app's own reminder entries and standing meetings are not things that happen this week
        event = d if a.own else (d.get("event") or {})
        if (a.repeats and not a.own) or (not a.own and event.get("repeats")):
            continue
        seen.add(a.snapshot)
        days = sorted(a.days)
        title = _one_line(a.title)
        last_day = days[-1] if days[-1] != days[0] else None
        if a.delivery is not None:
            kept = {k: v for k, v in a.delivery.items() if k not in ("tracking", "track", "order")}
            detail = ", ".join(
                f"{k}: {_one_line(v)}" for k, v in kept.items() if v not in (None, "", False) and k != "dated"
            )
            found.append(Item(a.snapshot, "delivery", days[0], last_day, title, detail))
            continue
        guests = bool(
            (d.get("attendees") or d.get("people") or d.get("invitation")) if a.own else (event.get("attendees"))
        )
        kind = "meeting" if guests else ("window" if last_day is not None else "entry")
        where = f"at {_one_line(a.where)}" if a.where else ""
        at = ""
        if not a.all_day and a.start:
            at = "at " + a.start[11:16] if len(a.start) >= 16 else ""
        found.append(Item(a.snapshot, kind, days[0], last_day, title, " ".join(x for x in (at, where) if x)))
    return found


def _fact_items(store: Any, first: date, last: date) -> list[Item]:
    view = store.read()
    found = []
    for fact in view.list("fact"):
        d = fact.data
        on = _day(d.get("on"))
        if on is None or not first <= on <= last or superseded_by(view, fact.id) is not None:
            continue
        found.append(
            Item(
                fact.id,
                "deadline",
                on,
                None,
                _one_line(d["text"]),
                _one_line(d.get("on_kind") or ""),
                d.get("trust") == "untrusted",
            )
        )
    return found


def _action_items(store: Any, cfg: Any, first: date, last: date) -> list[Item]:
    view = store.read()
    people = People(store, cfg)
    pm = people.pm
    found = []
    for a in view.list("action"):
        d = a.data
        if d.get("status") != "open" or d.get("reply_owed") or standing_hold(view, d, people):
            continue
        day = firm_due(d)
        if day is None or not first <= day <= last:
            continue
        mine = pm is not None and any(o.get("person") == pm for o in d.get("owners") or [])
        if not mine and pm not in (d.get("promised_to") or []):
            continue
        who = "" if mine else "promised to you"
        found.append(Item(a.id, "task", day, None, _one_line(d["text"]), who, d.get("trust") == "untrusted"))
    return found


def _away_periods(view: Any, cfg: Any) -> list[tuple[date, date]]:
    person = view.get("person", cfg.workspace.user.person) if cfg.workspace.user.person else None
    found = []
    for period in (person.data.get("away") or []) if person is not None else []:
        start = _day(period.get("start"))
        end = _day(period.get("end")) or start
        if start is not None and end is not None:
            found.append((start, end))
    return found


def _routine_items(store: Any, cfg: Any, first: date, last: date) -> list[Item]:
    """The kept routines the person's days away pause in the week, or let start again in it."""
    view = store.read()
    away = _away_periods(view, cfg)
    found = []
    for slot in routines.kept(view):
        happens = [
            first + timedelta(days=n)
            for n in range(7)
            if first + timedelta(days=n) <= last and (first + timedelta(days=n)).weekday() in slot.days
        ]
        paused = [d for d in happens if any(s <= d <= e for s, e in away)]
        if paused:
            found.append(
                Item(
                    slot.entry,
                    "routine",
                    paused[0],
                    paused[-1] if paused[-1] != paused[0] else None,
                    slot.label,
                    "paused while you are away",
                    False,
                )
            )
            continue
        for start, end in sorted(away):
            skipped = any(
                (start + timedelta(days=n)).weekday() in slot.days for n in range(min(7, (end - start).days + 1))
            )
            if not skipped:
                continue  # it never stopped, so it doesn't start again
            resumes = next(
                (end + timedelta(days=n) for n in range(1, 8) if (end + timedelta(days=n)).weekday() in slot.days), None
            )
            if resumes is not None and first <= resumes <= last:
                found.append(
                    Item(slot.entry, "routine", resumes, None, slot.label, "starts again after your days away", False)
                )
                break
    return found


def items(store: Any, cfg: Any, now: datetime, first: date, last: date) -> list[Item]:
    """Everything in the days from `first` through `last` the assistant may give a row, by day: each record once."""
    if first > last:
        return []
    found = [
        *_agenda_items(store, cfg, now, first, last),
        *_fact_items(store, first, last),
        *_action_items(store, cfg, first, last),
        *_routine_items(store, cfg, first, last),
    ]
    return sorted(found, key=lambda i: (i.first, _ORDER.index(i.kind), i.title.lower(), i.id))


def candidates(ws: Any, store: Any, cfg: Any, now: datetime) -> list[Item]:
    """The week's things that Today holds no line for: what a row may be made from."""
    first, last = ahead(cfg, now.astimezone(zone(cfg)).date())
    held = on_today(ws, store, cfg, now)
    return [i for i in items(store, cfg, now, first, last) if i.id not in held]


def touched_families(store: Any, after: int, kinds: list[str]) -> list[str]:
    """The screen families the writes after ledger position `after` touch beyond what their kinds name: the week ahead's
    card, when one of its own requests changed state (a request of any other task kind cannot change the card)."""
    if "request" not in kinds:
        return []
    view = store.read()
    for request_id in view.changed_ids(after, "request"):
        record = view.get("request", request_id)
        if record is not None and record.data.get("task") == TASK:
            return ["week-ahead"]
    return []


# ---- the checks ------------------------------------------------------------------------------------------------------


def problems(
    ws: Any,
    store: Any,
    cfg: Any,
    now: datetime,
    week: date,
    rows: list[Any],
    held: set[str] | None = None,
    sentence: str = "",
) -> list[str]:
    """What is wrong with a reading's rows, in plain words, or nothing. Exact checks: each row cites a record that
    exists and falls in the week, the row's days are in the week, each record has one row, nothing Today holds is
    repeated, and there are at most `steward.week_ahead.max_rows`. `held` is what Today held when the packet was built;
    without it, what Today holds now."""
    # Rows start from tomorrow, as of when the request was made: a row dated today is Today's, and is refused.
    last = week + timedelta(days=6)
    first = max(week, now.astimezone(zone(cfg)).date() + timedelta(days=1))
    found = {i.id: i for i in items(store, cfg, now, first, last)}
    if held is None:
        held = on_today(ws, store, cfg, now)
    most = cfg.steward.week_ahead.max_rows
    said: list[str] = []
    cited: set[str] = set()
    # Prose shown to the person never carries a day as year-month-day numbers.
    if any(_ISO_DAY.search(text or "") for text in [sentence, *(getattr(r, "words", "") for r in rows)]):
        said.append("write each day as a weekday, month and day (Fri, Nov 27), never as year-month-day numbers")
    for row in rows:
        source = row.source
        if source in cited:
            said.append(f"{source} has more than one row; give each record one row")
            continue
        cited.add(source)
        if source in held:
            said.append(f"{source} is already a line on Today, so the week ahead leaves it out")
        elif source not in found:
            said.append(f"{source} is not a record that falls in the week from {first} to {last}")
        end = row.to_day or row.from_day
        if row.from_day > last or end < first:
            said.append(f"the row for {source} is for days outside the week from {first} to {last}")
    if len(rows) > most:
        said.append(f"give at most {most} rows; this has {len(rows)}")
    return said


def check(ctx: Any, op: Any) -> list[str]:
    """The problems with a `week.read` op as the applier sees it: it is for the week of the request's `week_plan`, as of
    when the request was made."""
    from engine.workspace import Workspace

    request = ctx.store.read().get("request", ctx.inputs.request) if ctx.inputs.request else None
    about = (request.data.get("about") or {}) if request is not None else {}
    plan = ctx.store.read().get("week_plan", about.get("id")) if about.get("kind") == "week_plan" else None
    if plan is None:
        return ["a reading of the week is made for a week the person has a record for"]
    now = _stamp(request.data.get("created_at")) or datetime.now(UTC)
    ws = Workspace(ctx.store.path.parent)
    given = request.data.get("held_on_today")
    return problems(
        ws,
        ctx.store,
        ctx.cfg,
        now,
        date.fromisoformat(str(plan.data["week"])),
        list(op.rows),
        set(given) if given is not None else None,
        getattr(op, "sentence", "") or "",
    )


def apply(tx: Any, op: Any, ctx: Any, w: Any) -> list[dict[str, Any]]:
    """Keep a reading on the person's record for the week the request is for: its sentence and rows (each with the kind
    of record it cites), and when it was made."""
    request = tx.get("request", ctx.inputs.request) if ctx.inputs.request else None
    about = (request.data.get("about") or {}) if request is not None else {}
    plan = tx.get("week_plan", about["id"]) if about.get("kind") == "week_plan" else None
    if plan is None:
        raise StoreError("the week this reading was for is gone")
    now = _stamp(request.data.get("created_at")) or datetime.now(UTC)
    week = date.fromisoformat(str(plan.data["week"]))
    first = max(week, now.astimezone(zone(ctx.cfg)).date() + timedelta(days=1))
    kinds = {i.id: i.kind for i in items(ctx.store, ctx.cfg, now, first, week + timedelta(days=6))}
    rows = [
        {
            "from_day": r.from_day.isoformat(),
            "to_day": r.to_day.isoformat() if r.to_day and r.to_day != r.from_day else None,
            "words": _one_line(neutralize(r.words)),
            "source": r.source,
            "kind": kinds.get(r.source, "entry"),
        }
        for r in op.rows
    ]
    tx.update(
        "week_plan",
        plan.id,
        {"read_sentence": _one_line(neutralize(op.sentence)), "read_rows": rows, "read_at": ctx.store.clock()},
        w,
        read_version=plan.version,
    )
    return [{"kind": "week_plan", "id": plan.id}]


def _stamp(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# ---- asking for it ---------------------------------------------------------------------------------------------------


def _requests(view: Any, plan_id: str) -> list[Any]:
    return [
        r
        for r in view.list("request")
        if r.data["task"] == TASK and (r.data.get("about") or {}).get("id") == plan_id and not r.data.get("dismissed")
    ]


def _plan_for(store: Any, cfg: Any, now: datetime) -> tuple[str | None, date]:
    person = People(store, cfg).pm
    week, _ = week_of(cfg, now.astimezone(zone(cfg)).date())
    found = week_plan.plan_of(store.read(), person, week)
    return (found.id if found is not None else None), week


def _create(store: Any, cfg: Any, now: datetime, origin: str, context: WriteContext) -> str:
    person = People(store, cfg).pm
    week, _ = week_of(cfg, now.astimezone(zone(cfg)).date())
    with store.transaction() as tx:
        found = week_plan.plan_of(tx, person, week)
        plan_id = (
            found.id
            if found is not None
            else tx.create("week_plan", {"person": person, "week": week.isoformat()}, context).id
        )
        if any(r.data["state"] in IN_HAND for r in _requests(tx, plan_id)):
            raise StoreError("The assistant already has this week's reading in hand.")
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


def read_again(store: Any, cfg: Any, now: datetime) -> str:
    """The person's "Read the week again": queue a reading of this week, estimated first and held for their go above the
    configured amount. Returns the request. Refused while the assistant has one in hand."""
    return _create(store, cfg, now, "pm", _QUEUE)


def due(ws: Any, store: Any, cfg: Any, now: datetime) -> bool:
    """Whether this week's first reading is due: the person is set, nothing has been asked for the week yet (a try that
    failed or was declined is not asked again by itself) and something falls in it that Today doesn't hold."""
    from engine.dispatcher import person_is_set

    if not person_is_set(store, cfg):
        return False
    plan_id, _ = _plan_for(store, cfg, now)
    if plan_id is not None and _requests(store.read(), plan_id):
        return False
    return bool(candidates(ws, store, cfg, now))


def queue(ws: Any, store: Any, cfg: Any, now: datetime) -> str | None:
    """Queue the week's first reading when it is due, as a scheduled request. It then goes through the request path: its
    estimate, the person's go above the configured amount, its budget. Returns its id, or None."""
    if not due(ws, store, cfg, now):
        return None
    return _create(store, cfg, now, "schedule", _ENGINE)


def skip_reason(ws: Any, store: Any, cfg: Any, request: Any, now: datetime) -> str | None:
    """Why a reading has nothing to do any more, in plain words, or None: the week it was for is gone, or nothing
    falls in it any more. Decided before any packet, estimate or call."""
    about = request.get("about") or {}
    if store.read().get("week_plan", about.get("id")) is None:
        return "The week this reading was for is gone."
    if not candidates(ws, store, cfg, now):
        return "There is nothing dated in the week to read."
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
    """A reading was applied: the card shows it, so the run needs no review of its own and is done."""
    with store.transaction() as tx:
        found = tx.get("changeset", changeset_id)
        current = tx.get("request", request_id)
        if found is None or current is None or any(o["status"] == "held" for o in found.data["ops"]):
            return
        tx.update("request", request_id, {"state": "done", "waiting": None}, _ENGINE, read_version=current.version)


# ---- the packet ------------------------------------------------------------------------------------------------------


def _line(item: Item) -> str:
    span = item.first.isoformat() + (f" to {item.last.isoformat()}" if item.last else "")
    bits = [f"[{item.id}] {item.kind}", span, item.title]
    if item.detail:
        bits.append(item.detail)
    return " | ".join(bits)


def days_off_of(store: Any, cfg: Any, first: date, last: date) -> tuple[list[tuple[date, str]], int]:
    """The days off in the days from `first` through `last`, and the working days left in them (none off when the
    range is empty)."""
    from engine import days_off

    if first > last:
        return [], 0
    off = days_off.week_days_off(store.read(), cfg, People(store, cfg).pm, first, last)
    return off, days_off.working_days_between(cfg, first, last, [d for d, _ in off])


def lines(ws: Any, store: Any, cfg: Any, now: datetime) -> tuple[list[str], list[str]]:
    """The week's records as the packet shows them, and Today's lines (so they are not repeated)."""
    first, last = ahead(cfg, now.astimezone(zone(cfg)).date())
    held_lines: list[str] = []
    held: set[str] = set()
    for line in _today_lines(ws, store, cfg, now):
        ids = _ids_of(line)
        held |= ids
        words = _one_line(line.text or line.subject or "")
        if ids:
            held_lines.append(f"{' '.join(f'[{i}]' for i in sorted(ids))} {line.kind}: {words}".rstrip(": "))
    week = [_line(i) for i in items(store, cfg, now, first, last) if i.id not in held]
    return week, held_lines


_HELD_ID = re.compile(r"\[([^\[\]\s]+)\]")


def keep_held(store: Any, request_id: str, packet: Any) -> None:
    """Keep on the request the ids of the Today lines its packet was given (read from the packet's own block), so the
    reading is checked against what the packet told the assistant to leave out."""
    block = packet.task.request.split("# Lines Today already holds", 1)[-1]
    block = block.split(">", 1)[-1].split("</untrusted>", 1)[0]  # past the opening tag, up to the closing one
    ids = sorted(set(_HELD_ID.findall(block)))
    with store.transaction() as tx:
        current = tx.get("request", request_id)
        if current is not None:
            tx.update("request", request_id, {"held_on_today": ids}, _ENGINE, read_version=current.version)


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date) -> Any:
    """The packet for one reading. Stable first: the instructions, the op reference, the practice, what has been learned
    and the people on file. Then the request: the week's days, its records and Today's lines, marked as from outside."""
    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _people, _task
    from engine.prompts import render

    about = req.data.get("about") or {}
    plan = store.read().get("week_plan", about.get("id")) if about.get("kind") == "week_plan" else None
    if plan is None:
        raise PacketRefused("the week this reading was for is gone")
    zoned = _stamp(req.data.get("created_at")) or (
        datetime.combine(today, datetime.min.time(), tzinfo=zone(cfg)) + timedelta(hours=12)
    )
    week, held = lines(ws, store, cfg, zoned)
    if not week:
        raise PacketRefused("there is nothing dated in the week to read")
    first = date.fromisoformat(str(plan.data["week"]))
    start, _ = ahead(cfg, zoned.astimezone(zone(cfg)).date())
    people = _packet_people(store, cfg)
    off, working = days_off_of(store, cfg, start, first + timedelta(days=6))
    shown_week = neutralize("\n".join(week))
    shown_today = neutralize("\n".join(held)) if held else "(none)"
    learned = _learned(
        store, cfg, kind, people, projects=[], source=None, text=f"{shown_week}\n{shown_today}", today=today
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
        f"The week ahead runs from {start.isoformat()} (tomorrow; today is Today's) through "
        f"{(first + timedelta(days=6)).isoformat()}. "
        f"Give at most {cfg.steward.week_ahead.max_rows} rows.",
        (
            f"Days off in the week ahead: {_days_off_said(off)}. {working} working "
            f"{'day is' if working == 1 else 'days are'} left in it."
            if off
            else ""
        ),
        learned.per_input,
        f'# The week\'s records\n<untrusted source="{WEEK_BLOCK}">\n{shown_week}\n</untrusted>',
        "# Lines Today already holds (leave these out)\n"
        f'<untrusted source="{TODAY_BLOCK}">\n{shown_today}\n</untrusted>',
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


def _days_off_said(off: list[tuple[date, str]]) -> str:
    from engine import days_off

    return days_off.said(days_off._runs(off))


def _packet_people(store: Any, cfg: Any) -> Any:
    from engine.names import PacketPeople

    return PacketPeople(store, cfg)


# ---- what the screens show -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    from_day: date
    to_day: date | None
    words: str
    source: str
    kind: str
    #: The side of the record the row cites (None: on no side, shown under every choice of the side filter).
    side: str | None = None


@dataclass(frozen=True)
class Card:
    """The week ahead as the screens show it. `state`: read (the assistant's reading), rules (rows by rules, no
    sentence,
    because there is no reading), working (queued or running), needs_go (held for the person's go, with `estimate_usd`
    when there is one) or empty (nothing dated this week). `waiting` is why a reading did not come, in plain words, when
    it stopped. `rows` are what is shown now, never more than the configured most."""

    first: date
    last: date
    state: str
    sentence: str | None
    rows: tuple[Row, ...]
    request: str | None = None
    estimate_usd: float | None = None
    waiting: str | None = None
    hidden: int = 0
    #: The week ahead's days off (holidays and closures on the working week), each with its reason, and how many working
    #: days are left in it.
    days_off: tuple[tuple[date, str], ...] = ()
    working_days: int = 0


#: The kinds of record a row's source can be, in the order they are looked for.
_SOURCE_KINDS = ("action", "fact", "event", "snapshot", "glossary_entry")


def _side_of(view: Any, cfg: Any, source: str) -> str | None:
    """The side of the record a row cites, by the one shared function (None when it is on no side)."""
    for kind in _SOURCE_KINDS:
        record = view.get(kind, source)
        if record is not None:
            # A calendar event the app keeps no entry for is on the side its watched source serves.
            return sides.side_of_item(view, cfg, record) or (
                sides.watch_source_side(view, cfg, record.data.get("source")) if kind == "snapshot" else None
            )
    return None


def _rules_rows(found: list[Item], most: int, view: Any = None, cfg: Any = None) -> list[Row]:
    return [Row(i.first, i.last, i.title, i.id, i.kind, _side_of(view, cfg, i.id)) for i in found[:most]]


def card_of(ws: Any, store: Any, cfg: Any, now: datetime) -> Card:
    """The week ahead for the week `now` falls in. Reads only."""
    view = store.read()
    today = now.astimezone(zone(cfg)).date()
    first, last = week_of(cfg, today)
    start, _ = ahead(cfg, today)
    most = cfg.steward.week_ahead.max_rows
    plan = week_plan.plan_of(view, People(store, cfg).pm, first)
    held = on_today(ws, store, cfg, now)
    mine = {i.id: i for i in items(store, cfg, now, start, last)}
    aside = set(plan.data.get("set_aside") or []) if plan is not None else set()
    shown = [i for i in mine.values() if i.id not in held and i.id not in aside]
    off, _ = days_off_of(store, cfg, start, last)
    _, working = days_off_of(store, cfg, today, last)
    request = None
    if plan is not None:
        for r in sorted(_requests(view, plan.id), key=lambda r: (str(r.data["created_at"]), r.id), reverse=True):
            request = r
            break
    state_of = request.data["state"] if request is not None else None
    if plan is not None and plan.data.get("read_at"):
        kept = [
            Row(
                date.fromisoformat(str(r["from_day"])),
                date.fromisoformat(str(r["to_day"])) if r.get("to_day") else None,
                r["words"],
                r["source"],
                r["kind"],
                _side_of(view, cfg, r["source"]),
            )
            for r in plan.data.get("read_rows") or []
            if r["source"] in mine and r["source"] not in held and r["source"] not in aside
        ]
        rows = tuple(kept[:most])
        card = Card(
            first, last, "read", plan.data.get("read_sentence"), rows, days_off=tuple(off), working_days=working
        )
    else:
        card = Card(
            first,
            last,
            "rules" if shown else "empty",
            None,
            tuple(_rules_rows(shown, most, view, cfg)),
            days_off=tuple(off),
            working_days=working,
        )
    if request is not None and state_of in ("queued", "running"):
        return replace(card, state="working" if card.state != "read" else card.state, request=request.id)
    if request is not None and state_of == "needs_you":
        if request.data.get("approval") == "required":
            return replace(
                card,
                state="needs_go" if card.state != "read" else card.state,
                request=request.id,
                estimate_usd=request.data.get("estimate_usd"),
            )
        return replace(card, waiting=request.data.get("waiting"), request=request.id)
    return card


def set_aside(store: Any, cfg: Any, now: datetime, source: str) -> list[str]:
    """ "Not this week": leave one record out of this week's rows. Returns what was set aside before, which giving it
    back
    to `restore` undoes. A signal is recorded so the assistant's reading is judged by it."""
    person = People(store, cfg).pm
    week, _ = week_of(cfg, now.astimezone(zone(cfg)).date())
    with store.transaction() as tx:
        found = week_plan.plan_of(tx, person, week)
        before = list(found.data.get("set_aside") or []) if found is not None else []
        if source in before:
            return before
        values = {"set_aside": [*before, source]}
        if found is None:
            tx.create("week_plan", {"person": person, "week": week.isoformat(), **values}, _SET_ASIDE)
        else:
            tx.update("week_plan", found.id, values, _SET_ASIDE, read_version=found.version)
    from engine.dispatcher import signal

    signal(store, "suggestion_dismissed", [source], note=f"Not this week: {source} left out of the week ahead", now=now)
    return before


def restore(store: Any, cfg: Any, now: datetime, before: list[str]) -> None:
    """Give back what `set_aside` returned: the week's set-aside list as it was."""
    person = People(store, cfg).pm
    week, _ = week_of(cfg, now.astimezone(zone(cfg)).date())
    with store.transaction() as tx:
        found = week_plan.plan_of(tx, person, week)
        if found is not None:
            tx.update("week_plan", found.id, {"set_aside": before}, _SET_ASIDE, read_version=found.version)
