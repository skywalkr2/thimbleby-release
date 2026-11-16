"""The weekly look at the person (design 6.22, "Learning the person from their mail and calendar"): one run, once a
week and once after the first read, that is given the top entries of the contact tally (counts and names, never message
text), the calendar's repeating entries (title and time) and the people already on file, and proposes through the
ordinary knowledge proposals: who the person's people and organizations are and who answers what.

Nothing it proposes is used until the person keeps it. Proposals join the day's one review card, merge with each other
and with what is kept, and expire unreviewed like proposals from inputs. What the person discarded is left out of the
next packet, so it is never offered again. The run is a request of the `knowledge-person` kind: estimated first, held
for the person's go above the configured amount, with its own budget.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from engine import contact_tally
from engine import people_suggestions as ps
from engine.contacts import all_values
from engine.proposals import _decisions, _norm
from engine.storage import WriteContext
from engine.today import zone
from engine.untrusted import neutralize

TASK = "knowledge-person"
_ENGINE = WriteContext(actor="engine", trust="trusted", op="person_look.queue")
_DONE = WriteContext(actor="engine", trust="trusted", op="person_look.finish")
#: The states in which a look is still open: queued, with the assistant, or waiting for the person's go.
OPEN_STATES = ("queued", "running", "needs_you", "review")
NOTHING_NEW = "Nothing new to suggest."
SWITCHED_OFF = "The look at who you deal with is switched off."
NOTHING_TO_LOOK_AT = "There is nothing new about who you deal with to look at."
#: How the person's mail names the lines of the tally a run is shown, so the stand-in and a model quote them whole.
TALLY_BLOCK = "contact-tally"
SERIES_BLOCK = "repeating-entries"


def _one_line(text: str) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def _on_file(store: Any) -> dict[str, str]:
    """Each address of a person on file (lower case) to that person's id."""
    return {
        v.lower(): p.id for p in store.read().list("person") for v in all_values(p.data.get("how_to_reach")) if "@" in v
    }


def _already_decided(view: Any) -> set[str]:
    """The names (normalized) the assistant has no reason to propose again: a glossary entry that is kept or waiting for
    the person, or that the person discarded (a discard is never made again, however long ago)."""
    decided = _decisions(view)
    names: set[str] = set()
    for entry in view.list("glossary_entry"):
        status = entry.data.get("status")
        said_no = status == "discarded" and (decided.get(entry.id) or ("", None))[0] == "discarded"
        if status in ("active", "proposed") or said_no:
            names.add(_norm(entry.data.get("term")))
    return names - {""}


#: Lines that stand in for the tally and the repeating entries (set by the evaluation harness, which has no mailbox):
#: `(tally_lines, series_lines)`, or None for the real ones.
_stand_in_lines: tuple[list[str], list[str]] | None = None


def use_lines(contacts: list[str] | None, series: list[str] | None = None) -> None:
    """Make the look read these lines in place of the tally and the calendar's repeating entries; `None` for the
    contacts goes back to the real ones. For evaluation cases, which carry a fictional tally."""
    global _stand_in_lines
    _stand_in_lines = None if contacts is None else (list(contacts), list(series or []))


def shown_contacts(store: Any, cfg: Any) -> list[tuple[contact_tally.Contact, str | None]]:
    """The tally entries a run is shown with the id of the person on file for each, the most dealt with first: not kept
    apart, with at least `person_look_min_messages` messages, at most `person_look_entries`. Someone on file is shown
    (it is who routing may name); someone not on file is left out when a glossary entry already names them or the
    person discarded one."""
    settings = cfg.dispatch.knowledge
    on_file = _on_file(store)
    decided = _already_decided(store.read())
    found: list[tuple[contact_tally.Contact, str | None]] = []
    for c in contact_tally.tally(store, cfg):
        if c.apart is not None or c.total < settings.person_look_min_messages:
            continue
        person = on_file.get(c.address)
        if person is None and _norm(c.name) in decided:
            continue
        found.append((c, person))
    return found[: settings.person_look_entries]


def tally_lines(store: Any, cfg: Any) -> list[str]:
    """The lines of the tally a run is shown: the address, the name, the counts each way, the first and last day, the
    sides the sources serve and who it is on file. Headers only: no subject and no text."""
    if _stand_in_lines is not None:
        return list(_stand_in_lines[0])
    lines = []
    for c, person in shown_contacts(store, cfg):
        days = f"{c.first} to {c.last}" if c.first and c.last else "no day"
        bits = [
            c.address,
            _one_line(c.name),
            f"{c.from_them} from them, {c.to_them} to them",
            days,
            "sides: " + (", ".join(c.sides) or "none"),
        ]
        if person:
            bits.append(f"on file: {person}")
        lines.append(" | ".join(bits))
    return lines


def _clock(value: Any, here: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(here) if moment.tzinfo else moment.replace(tzinfo=here)


def _slot_of(event: dict[str, Any], here: Any) -> tuple[str, str, str] | None:
    """Where a timed calendar entry sits in a week: the weekday (lower case), its start and its end as HH:MM on the
    person's clock. None for a day-long entry, one with no readable time or one that ends on another day."""
    if event.get("all_day"):
        return None
    start, end = _clock(event.get("start"), here), _clock(event.get("end"), here)
    if start is None or end is None or end.date() != start.date() or end <= start:
        return None
    return start.strftime("%A").lower(), start.strftime("%H:%M"), end.strftime("%H:%M")


def _decided_slots(view: Any) -> set[tuple[str, str, str]]:
    """The slots (weekday, start, end) of routines already kept, waiting for the person or discarded for good: a slot
    the person has ruled on is not shown again, whatever it is called now."""
    decided = _decisions(view)
    found: set[tuple[str, str, str]] = set()
    for entry in view.list("glossary_entry"):
        routine = entry.data.get("routine")
        if not routine:
            continue
        status = entry.data.get("status")
        said_no = status == "discarded" and (decided.get(entry.id) or ("", None))[0] == "discarded"
        if status in ("active", "proposed") or said_no:
            found |= {(day, routine["start"], routine["end"]) for day in routine["days"]}
    return found


def _slot_text(slot: tuple[str, str, str]) -> str:
    return f"{slot[0].capitalize()} {slot[1]}-{slot[2]}"


def series_lines(store: Any, cfg: Any) -> list[str]:
    """The calendar's repeating entries, one line each: the title, the day of the week and the time of its first date
    and the repeat rule as its source wrote it. Then the slots kept week after week with no repeat rule: entries with
    the same title, weekday and times on at least `person_look_slot_weeks` different weeks. Titles and times only;
    entries called off or gone are left out, and so is a slot a routine already holds (kept, waiting or discarded)."""
    if _stand_in_lines is not None:
        return list(_stand_in_lines[1])
    settings = cfg.dispatch.knowledge
    limit = settings.person_look_series
    here = zone(cfg)
    view = store.read()
    ruled_on = _decided_slots(view)
    names = _already_decided(view)
    seen: set[str] = set()
    lines: list[str] = []
    snaps = [s for s in view.list("snapshot") if s.data.get("event") and not s.data.get("gone")]
    titles: set[str] = set()
    weeks: dict[tuple[str, tuple[str, str, str]], tuple[str, set[tuple[int, int]]]] = {}
    for snap in sorted(snaps, key=lambda s: (str(s.data.get("title")).lower(), s.id)):
        event = snap.data["event"]
        if event.get("cancelled"):
            continue
        title = _one_line(snap.data.get("title"))
        slot = _slot_of(event, here)
        if not event.get("repeats"):
            start = _clock(event.get("start"), here)
            if slot is not None and start is not None and title:
                _, found = weeks.setdefault((_norm(title), slot), (title, set()))
                found.add(tuple(start.isocalendar()[:2]))
            continue
        titles.add(_norm(title))
        if (slot is not None and slot in ruled_on) or _norm(title) in names:
            continue
        start = _clock(event.get("start"), here)
        when = "no time"
        if start is not None:
            when = start.strftime("%A") + ("" if event.get("all_day") else start.strftime(" %H:%M"))
            end = _clock(event.get("end"), here)
            if end is not None and not event.get("all_day"):
                when += end.strftime("-%H:%M")
        line = f"{title} | {when} | repeats: {_one_line(event['repeats'])[:80]}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    for (key, slot), (title, found) in sorted(weeks.items(), key=lambda kv: (kv[1][0].lower(), kv[0][1])):
        if len(found) < settings.person_look_slot_weeks or key in titles or key in names or slot in ruled_on:
            continue
        line = f"{title} | {_slot_text(slot)} | repeats: same time on {len(found)} different weeks, no repeat rule"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return lines[: max(0, limit)]


def has_something_to_look_at(store: Any, cfg: Any) -> bool:
    return bool(tally_lines(store, cfg)) or bool(series_lines(store, cfg))


def _level(store: Any, cfg: Any) -> str:
    """The most sensitive data level of the mail and calendar sources the tally and the entries are read from."""
    from engine.watch import data_level_of

    levels = ("open", "internal", "restricted")
    kinds = ps._mail_sources(store, cfg)
    names = {s.id for s in kinds}
    snaps = {s.data["source"] for s in store.read().list("snapshot") if s.data.get("event")}
    names |= snaps
    found = [data_level_of(cfg, s) for s in cfg.watch.sources if s.enabled and s.id in names]
    return max(found, key=levels.index, default="internal")


# ---- when it runs ----------------------------------------------------------------------------------------------------


def last_look(view: Any) -> datetime | None:
    """When the latest look was queued."""
    moments = []
    for r in view.list("request"):
        if r.data["task"] == TASK and r.data.get("created_at"):
            try:
                moments.append(datetime.fromisoformat(str(r.data["created_at"])))
            except ValueError:
                continue
    return max(moments, default=None)


def due(store: Any, cfg: Any, now: datetime) -> bool:
    """Whether a look is due: it is on, none is open, the last was queued at least `person_look_every_days` ago (or none
    ever was, which is the look after the first read), and there is something to look at."""
    settings = cfg.dispatch.knowledge
    if not settings.person_look:
        return False
    view = store.read()
    if any(r.data["task"] == TASK and r.data["state"] in OPEN_STATES for r in view.list("request")):
        return False
    last = last_look(view)
    if last is not None:
        stamp = last if last.tzinfo else last.replace(tzinfo=now.tzinfo)
        if now - stamp < timedelta(days=settings.person_look_every_days):
            return False
    return has_something_to_look_at(store, cfg)


def queue(store: Any, cfg: Any, now: datetime) -> str | None:
    """Queue the look when it is due and the person is set, as a scheduled request. Returns its id, or None. It then
    goes through the request path: its estimate, the person's go above the configured amount, its budget."""
    from engine.dispatcher import person_is_set

    if not person_is_set(store, cfg) or not due(store, cfg, now):
        return None
    return _create(store, cfg, now)


def _create(store: Any, cfg: Any, now: datetime) -> str:
    with store.transaction() as tx:
        made = tx.create(
            "request",
            {
                "task": TASK,
                "origin": "schedule",
                "state": "queued",
                "waiting": "With the assistant, starting now",
                "sensitivity": _level(store, cfg),
                "created_at": now.isoformat(),
            },
            _ENGINE,
        )
    return made.id


def skip_reason(store: Any, cfg: Any, request: Any) -> str | None:
    """Why a look has nothing to do any more, in plain words, or None: it was switched off, or there is nothing left to
    look at. Decided before any packet, estimate or call."""
    if not cfg.dispatch.knowledge.person_look:
        return SWITCHED_OFF
    if not has_something_to_look_at(store, cfg):
        return NOTHING_TO_LOOK_AT
    return None


def close(store: Any, request_id: str, why: str) -> None:
    with store.transaction() as tx:
        current = tx.get("request", request_id)
        if current is not None and (current.data["state"], current.data.get("waiting")) != ("done", why):
            tx.update(
                "request",
                request_id,
                {"state": "done", "waiting": why, "cause": None},
                _DONE,
                read_version=current.version,
            )


def finish(store: Any, request_id: str, changeset_id: str) -> None:
    """A look was applied. Its proposals are on the review card, so the run itself needs no review: it is done, unless a
    change in it waits for the person."""
    with store.transaction() as tx:
        found = tx.get("changeset", changeset_id)
        current = tx.get("request", request_id)
        if found is None or current is None or any(o["status"] == "held" for o in found.data["ops"]):
            return
        waiting = None if found.data["ops"] else NOTHING_NEW
        tx.update("request", request_id, {"state": "done", "waiting": waiting}, _DONE, read_version=current.version)


# ---- the packet ------------------------------------------------------------------------------------------------------


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date) -> Any:
    """The packet for one look. Stable first: the instructions, the op reference, the practice, what has been learned
    and the people on file. Then the request: the tally's lines and the repeating entries, marked as from outside."""
    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.names import PacketPeople
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _people, _task
    from engine.prompts import render

    contacts = tally_lines(store, cfg)
    series = series_lines(store, cfg)
    if not contacts and not series:
        raise PacketRefused("there is nothing about who the person deals with to look at")
    shown_tally = neutralize("\n".join(contacts)) if contacts else "(none)"
    shown_series = neutralize("\n".join(series)) if series else "(none)"
    people = PacketPeople(store, cfg)
    learned = _learned(
        store, cfg, kind, people, projects=[], source=None, text=f"{shown_tally}\n{shown_series}", today=today
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
        learned.per_input,
        f'# Who the person deals with (counts only)\n<untrusted source="{TALLY_BLOCK}">\n{shown_tally}\n</untrusted>',
        f'# Their repeating calendar entries\n<untrusted source="{SERIES_BLOCK}">\n{shown_series}\n</untrusted>',
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
        cites=f"{TASK}:{req.id}",
        data_level=_data_level(store, req.data),
        knowledge=learned.log,
    )
