"""The weekly look at the person (design 6.22, "Learning the person from their mail and calendar"): one run, once a
week and once after each mail account's first read, that is given the top entries of the contact tally (counts, names
and the marks an address shows, never message text), the calendar's repeating entries (title and time) and the people
already on file, and proposes: who the person's people and organizations are, who answers what (the ordinary knowledge
proposals), and the people to add to the people on file (`person.offer`, each with a line saying why).

Who is a person to the user is the run's reading. The tally only counts and drops the person's own addresses and what
they set aside; this module also leaves out addresses already on file and ones already offered or left out. A role
address, a code in an address, a company word in a name, bulk mail and the rest reach the run as hints beside the line,
never as a verdict: a recruiter writes from a role address, a tradesperson's name reads as a company, a person's address
may carry a tag, and a newsletter's sender is no one to add.

Nothing it proposes is used until the person keeps it. Knowledge proposals join the day's one review card, merge with
each other and with what is kept, and expire unreviewed like proposals from inputs. People offers are ongoing, from
every look: they are a line of their own on Today (`people_offers`) and are shown in the People step too while the
person is on it, and each is kept by the person's own add in one change named for the person added; an offer left out
is never made again. What the person discarded is
left out of the next packet, so it is never offered again. The run is a request of the `knowledge-person` kind:
estimated first, held for the person's go above the configured amount, with its own budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine import contact_tally, mail_headers, sides
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
HABITS_BLOCK = "mail-habits"


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


def _asked_before(view: Any, own: str | None) -> set[tuple[str, tuple[int, int] | None]]:
    """What an earlier look read and finished with (offered or not), as each address with the counts it showed then
    (messages from them, to them; none for a look made before counts were kept): the assistant is not asked about the
    same address again until its counts change. A look closed with no call, or one that failed, asked about nothing;
    `own` is the look being asked for now, whose own addresses count for nothing here."""
    found: set[tuple[str, tuple[int, int] | None]] = set()
    for r in view.list("request"):
        if r.data["task"] == TASK and r.id != own and r.data["state"] in ("done", "review"):
            counts = r.data.get("asked_counts") or {}
            for a in r.data.get("asked_about") or []:
                seen = counts.get(str(a).lower())
                found.add((str(a).lower(), (int(seen[0]), int(seen[1])) if seen else None))
    return found


def _counts_of(lines: list[str]) -> dict[str, list[int]]:
    """The counts each tally line shows for its address: `[from them, to them]`."""
    found: dict[str, list[int]] = {}
    for line in lines:
        counts = re.search(r"(\d+) from them, (\d+) to them", line)
        address = line.split(" | ")[0].strip().lower()
        if counts and "@" in address:
            found[address] = [int(counts.group(1)), int(counts.group(2))]
    return found


def _offered_addresses(view: Any) -> set[str]:
    """The addresses a person offer was made for, whatever became of it: waiting, kept or left out."""
    return {str(o.data["address"]).lower() for o in view.list("person_offer")}


#: Lines that stand in for the tally and the repeating entries (set by the evaluation harness, which has no mailbox):
#: `(tally_lines, series_lines)`, or None for the real ones.
_stand_in_lines: tuple[list[str], list[str]] | None = None


def use_lines(contacts: list[str] | None, series: list[str] | None = None) -> None:
    """Make the look read these lines in place of the tally and the calendar's repeating entries; `None` for the
    contacts goes back to the real ones. For evaluation cases, which carry a fictional tally."""
    global _stand_in_lines
    _stand_in_lines = None if contacts is None else (list(contacts), list(series or []))


def shown_contacts(store: Any, cfg: Any, own: str | None = None) -> list[tuple[contact_tally.Contact, str | None]]:
    """The tally entries a run is shown with the id of the person on file for each: not kept apart, with at least
    `person_look_min_messages` messages, at most `person_look_entries`; those the person writes to first, then those
    no look has read, each group the most dealt with first. Someone on file is shown
    (it is who routing may name); someone not on file is left out when a glossary entry already names them or the
    person discarded one, or an earlier look already read their address with the counts it has now (`own` is the look
    being made now)."""
    settings = cfg.dispatch.knowledge
    on_file = _on_file(store)
    decided = _already_decided(store.read())
    offered = _offered_addresses(store.read())
    asked = _asked_before(store.read(), own)
    read_before = {address for address, _counts in asked}
    found: list[tuple[contact_tally.Contact, str | None]] = []
    for c in contact_tally.tally(store, cfg):
        if c.apart is not None or c.total < settings.person_look_min_messages:
            continue
        person = on_file.get(c.address)
        unchanged = (c.address, None) in asked or (c.address, (c.from_them, c.to_them)) in asked
        if person is None and (_norm(c.name) in decided or c.address in offered or unchanged):
            continue
        found.append((c, person))
    # The tally comes most dealt with first. When more stand than a run is shown, those the person writes to come
    # before those who only write to the person, and an address no look has read before one read with other counts,
    # so the busiest senders never crowd the rest out look after look. An order only: nobody is left out by it for good.
    found.sort(key=lambda pair: (not pair[0].wrote_to, pair[0].address in read_before))
    return found[: settings.person_look_entries]


def tally_lines(store: Any, cfg: Any, own: str | None = None) -> list[str]:
    """The lines of the tally a run is shown: the address, the name, the counts each way, the first and last day, the
    sides the sources serve, the hints the address shows and who it is on file. Headers only: no subject and no text."""
    if _stand_in_lines is not None:
        return list(_stand_in_lines[0])
    lines = []
    names = sides.side_names(store.read(), cfg)
    for c, person in shown_contacts(store, cfg, own):
        shown_sides = [_one_line(names.get(i) or i) for i in c.sides]
        days = f"{c.first} to {c.last}" if c.first and c.last else "no day"
        bits = [
            c.address,
            _one_line(c.name),
            f"{c.from_them} from them, {c.to_them} to them",
            days,
            "sides: " + (", ".join(shown_sides) or "none"),
        ]
        if c.hints:
            bits.append("hints: " + ", ".join(contact_tally.HINT_WORDS[h] for h in c.hints))
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


def has_something_to_look_at(store: Any, cfg: Any, own: str | None = None) -> bool:
    return bool(tally_lines(store, cfg, own)) or bool(series_lines(store, cfg))


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


#: The outcomes of a read that settle a source's first reading: it was read, or it couldn't be and says so on Mail.
READ_OUTCOMES = ("ok", "baseline", "failed")


def read_sources_of(store: Any, cfg: Any, ws: Any = None) -> list[Any]:
    """The mail and calendar sources whose first read the look waits for: the enabled ones that read, and (given the
    workspace) whose account is not signed out or expired."""
    from engine import setup
    from engine.connectors import CORE, declared_reads, reads

    said = declared_reads({**CORE, **store.plugins.connectors()})
    if ws is not None:
        return setup.read_sources(ws, cfg, store, said)
    return [s for s in cfg.watch.sources if s.enabled and reads(s.connector, said)]


def first_read_standing(view: Any, sources: list[Any], now: datetime) -> tuple[list[Any], list[tuple[Any, datetime]]]:
    """Where the first reads stand: the sources not read once, as `(pending, waiting)`. A source whose latest try was
    answered with a wait the service asked for, and whose time has not come, is waiting (with that time), never
    pending: it is not a failure and it is not being read."""
    pending: list[Any] = []
    waiting: list[tuple[Any, datetime]] = []
    for source in sources:
        runs = view.find("watch_run", {"source": source.id})
        if any(r.data["outcome"] in READ_OUTCOMES for r in runs):
            continue
        last = runs[-1] if runs else None
        until = (
            _clock(last.data.get("retry_at"), UTC) if last is not None and last.data["outcome"] == "throttled" else None
        )
        if until is not None and until > now:
            waiting.append((source, until))
        else:
            pending.append(source)
    return pending, waiting


def first_reads_in(store: Any, cfg: Any, now: datetime, ws: Any = None) -> bool:
    """Whether every mail and calendar source was read once (or could not be and says so on Mail). A source waiting
    for the service is not read yet."""
    pending, waiting = first_read_standing(store.read(), read_sources_of(store, cfg, ws), now)
    return not pending and not waiting


def _sweeps(view: Any, cfg: Any) -> list[dict[str, Any]]:
    """Where the rest of each mail source's headers stands, for those still being read (not given up on)."""
    found = []
    for source in cfg.watch.sources:
        state = mail_headers.sweep_waiting(view, source.id) if source.enabled else None
        if state and not state.get("gave_up"):
            found.append(state)
    return found


def header_sample_in(store: Any, cfg: Any) -> bool:
    """Whether the look has headers to count: no mail source's headers are still waiting to be read with none kept yet
    (the sample a first sign-in takes was refused or slowed down by the service, and the rest waits for its time). A
    source whose headers can't be read, or whose read was given up on, holds nothing back."""
    return all(int(state.get("taken", 0)) > 0 for state in _sweeps(store.read(), cfg))


def more_mail_coming(store: Any, cfg: Any) -> bool:
    """Whether the rest of a mail source's year of headers is still being read: the tally is still growing."""
    return bool(_sweeps(store.read(), cfg))


def headers_kept_since(view: Any, moment: datetime) -> bool:
    """Whether a page of the rest of a mail source's headers was kept after `moment`."""
    for run in view.list("watch_run"):
        kept = _clock((run.data.get("header_sweep") or {}).get("kept_at"), moment.tzinfo or UTC)
        if kept is not None and kept > moment:
            return True
    return False


def header_sweep_finished_since(view: Any, moment: datetime) -> bool:
    """Whether the sweep of the rest of a mail source's headers ended after `moment`."""
    for run in view.list("watch_run"):
        ended = _clock(run.data.get("header_sweep_finished_at"), moment.tzinfo or UTC)
        if ended is not None and ended > moment:
            return True
    return False


def settled_since(view: Any, moment: datetime) -> bool:
    """Whether a read finished after `moment` that can change the tally: a mail source's first read, an older read
    that ran to its end (or stopped for the person), or the header sweep."""
    if first_read_since(view, moment):
        return True
    for run in view.list("watch_run"):
        finished = _clock(run.data.get("older_finished_at"), moment.tzinfo or UTC)
        if finished is not None and finished > moment:
            return True
    return header_sweep_finished_since(view, moment)


def due(store: Any, cfg: Any, now: datetime, ws: Any = None) -> bool:
    """Whether a look is due: it is on, none is open, every first read is in (and the header sample), and the last was
    queued at least `person_look_every_days` ago (or none ever was, which is the look after the first reads), with
    something to look at. Inside the week another look is due when a read finished since the last one (a first read,
    an older read or the header sweep), or, while nobody has been offered yet, when more of the year's headers came
    in, and the tally shows an address new or with other counts than any look read."""
    settings = cfg.dispatch.knowledge
    if not settings.person_look:
        return False
    view = store.read()
    if any(r.data["task"] == TASK and r.data["state"] in OPEN_STATES for r in view.list("request")):
        return False
    if not first_reads_in(store, cfg, now, ws) or not header_sample_in(store, cfg):
        return False
    last = last_look(view)
    if last is not None:
        stamp = last if last.tzinfo else last.replace(tzinfo=now.tzinfo)
        if now - stamp < timedelta(days=settings.person_look_every_days):
            # While nobody has been offered yet, each page of the year's headers that comes in is looked at too, so the
            # first offers don't wait for the whole year to be read.
            more = settled_since(view, stamp) or (not view.list("person_offer") and headers_kept_since(view, stamp))
            return more and bool(tally_lines(store, cfg))
    return has_something_to_look_at(store, cfg)


def first_read_since(view: Any, moment: datetime) -> bool:
    """Whether a mail source was taken in (its first read, which noted how far back it looked) after `moment`."""
    for run in view.list("watch_run"):
        if not run.data.get("looked_back_to"):
            continue
        started = _clock(run.data.get("started_at"), moment.tzinfo or UTC)
        if started is not None and started > moment:
            return True
    return False


def queue(store: Any, cfg: Any, now: datetime, ws: Any = None) -> str | None:
    """Queue the look when it is due and the person is set, as a scheduled request. Returns its id, or None. It then
    goes through the request path: its estimate, the person's go above the configured amount, its budget."""
    from engine.dispatcher import person_is_set

    if not person_is_set(store, cfg) or not due(store, cfg, now, ws):
        return None
    return _create(store, cfg, now)


def addresses_of(lines: list[str]) -> list[str]:
    """The addresses of the tally lines of people not on file, in lower case: the ones an offer may name."""
    found = []
    for line in lines:
        parts = [p.strip() for p in line.split(" | ")]
        if parts and "@" in parts[0] and not any(p.startswith("on file:") for p in parts):
            found.append(parts[0].lower())
    return found


def _create(store: Any, cfg: Any, now: datetime) -> str:
    lines = tally_lines(store, cfg)
    asked = addresses_of(lines)
    counts = _counts_of(lines)
    with store.transaction() as tx:
        made = tx.create(
            "request",
            {
                "task": TASK,
                "origin": "schedule",
                "state": "queued",
                "waiting": "With the assistant, starting now",
                "sensitivity": _level(store, cfg),
                "asked_about": asked,
                "asked_counts": {a: counts[a] for a in asked if a in counts},
                "created_at": now.isoformat(),
            },
            _ENGINE,
        )
    return made.id


def skip_reason(store: Any, cfg: Any, request: Any, request_id: str | None = None) -> str | None:
    """Why a look has nothing to do any more, in plain words, or None: it was switched off, or there is nothing left to
    look at. Decided before any packet, estimate or call."""
    if not cfg.dispatch.knowledge.person_look:
        return SWITCHED_OFF
    if not has_something_to_look_at(store, cfg, request_id):
        return NOTHING_TO_LOOK_AT
    return None


def close(store: Any, request_id: str, why: str) -> None:
    with store.transaction() as tx:
        current = tx.get("request", request_id)
        if current is not None and (current.data["state"], current.data.get("waiting")) != ("done", why):
            tx.update(
                "request",
                request_id,
                {"state": "done", "waiting": why, "cause": None, "asked_about": None, "asked_counts": None},
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


# ---- the offers ------------------------------------------------------------------------------------------------------


def _sorted_out(ctx: Any, op: Any) -> tuple[list[Any], list[str]]:
    """The entries of a `person.offer` op that stand, and what is wrong with each of the others in plain words: an
    address stands when the request's packet listed it, it is not on file, it was not offered or left out before and
    it was not named earlier in the op."""
    view = ctx.store.read()
    request = view.get("request", ctx.inputs.request) if ctx.inputs.request else None
    listed = {str(a).lower() for a in ((request.data.get("asked_about") if request is not None else None) or [])}
    on_file = set(_on_file(ctx.store))
    before = _offered_addresses(view)
    good: list[Any] = []
    said: list[str] = []
    seen: set[str] = set()
    for person in op.people:
        address = person.address.strip().lower()
        if address not in listed:
            said.append(f"{person.address} is not an address the list holds")
        elif address in on_file:
            said.append(f"{person.address} is on file already")
        elif address in before:
            said.append(f"{person.address} was offered before")
        elif address in seen:
            said.append(f"{person.address} is offered twice")
        else:
            good.append(person)
        seen.add(address)
    return good, said


def check(ctx: Any, op: Any) -> list[str]:
    """The problems with a `person.offer` op as the applier sees it, in plain words. An entry that doesn't stand is left
    out when the op is applied and the others are kept, so the op is refused only when it names people and none of
    them stands."""
    good, said = _sorted_out(ctx, op)
    return said if op.people and not good else []


def _counts(store: Any, cfg: Any, address: str, own: str | None) -> tuple[int, int]:
    """The messages from them and to them the tally's line for an address shows, or none."""
    for line in tally_lines(store, cfg, own):
        if line.split(" | ")[0].strip().lower() == address:
            found = re.search(r"(\d+) from them, (\d+) to them", line)
            if found:
                return int(found.group(1)), int(found.group(2))
    return 0, 0


#: Phrases of the app's own workings an offer's reason may still hold, and the plain words they become.
_PLAIN_WORDS = (
    (re.compile(r"(?i)\b(?:in|from|on) (?:this|the|that) (?:tally|list|packet)\b"), "in your mail"),
    (re.compile(r"(?i)\b(?:this|the|that|your) (?:tally|packet)\b"), "your mail"),
    (re.compile(r"(?i)\bthe list\b"), "your mail"),
    (re.compile(r"(?i)\btally\b"), "mail"),
)


def plain_reason(text: str, view: Any, cfg: Any) -> str:
    """An offer's reason as the person reads it: a side's id is the side's name, and the app's own words for where the
    counts came from ("the tally", "the list") are said as "your mail". The model's own sentence is kept otherwise."""
    names = sides.side_names(view, cfg)
    for side_id in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-z0-9-]){re.escape(side_id)}(?![A-Za-z0-9])", names[side_id] or "your mail", text)
    for pattern, plain in _PLAIN_WORDS:
        text = pattern.sub(plain, text)
    return text


def apply(tx: Any, op: Any, ctx: Any, w: Any) -> list[dict[str, Any]]:
    """Keep each person who stands as an offer that waits for the person: name, address, why and the counts, as of
    now. An entry that doesn't stand (`_sorted_out`) is left out and takes no other with it."""
    made = []
    now = ctx.store.clock()
    for person in _sorted_out(ctx, op)[0]:
        address = person.address.strip().lower()
        from_them, to_them = _counts(ctx.store, ctx.cfg, address, ctx.inputs.request)
        offer = tx.create(
            "person_offer",
            {
                "name": " ".join(neutralize(person.name).split())[:80],
                "address": address,
                "why": " ".join(neutralize(plain_reason(person.why, ctx.store.read(), ctx.cfg)).split())[:240],
                **({"relation": rel} if (rel := " ".join(neutralize(person.relation or "").split())[:60]) else {}),
                "from_them": from_them,
                "to_them": to_them,
                "status": "offered",
                "offered_at": now,
            },
            w,
        )
        made.append({"kind": "person_offer", "id": offer.id})
    return made


def waiting_offers(store: Any) -> list[Any]:
    """The offers waiting for the person, the ones from the most messages first, then by name."""
    found = waiting_offers_in(store.read())
    return sorted(found, key=lambda o: (-(o.data["from_them"] + o.data["to_them"]), o.data["name"].lower(), o.id))


def settle(store: Any, cfg: Any, address: str, status: str, person: str | None = None) -> str | None:
    """Mark the waiting offer for an address kept (with the person it became) or dismissed, as the person's own edit.
    A dismissal records a signal. Returns the change's id (which Undo takes back), or None when there was no offer."""
    from engine.applier import apply_as_person

    for offer in store.read().list("person_offer"):
        if offer.data["address"].lower() == address.strip().lower() and offer.data["status"] == "offered":
            fields: dict[str, Any] = {"status": status}
            if person:
                fields["person"] = person
            changeset = apply_as_person(
                store,
                cfg,
                [
                    {
                        "op": "record.edit",
                        "record": {"kind": "person_offer", "id": offer.id},
                        "fields": fields,
                        "read_version": offer.version,
                    }
                ],
                f"Added {offer.data['name']}" if status == "kept" else f"Left out {offer.data['name']}",
            )
            if status == "dismissed":
                _rejected(store, offer.id)
            return changeset
    return None


def _rejected(store: Any, offer_id: str) -> None:
    """The person said no to someone the assistant offered: a signal, so the repeat-correction rate sees it. It queues
    no learning (the offer is never made again, which is what it teaches)."""
    from engine.dispatcher import signal

    signal(store, "discarded", [offer_id], note="Not this one: left out of the people the assistant offered")


def find_waiting(view: Any, offer_id: str) -> Any | None:
    """The offer with this id when it still waits for the person and its address and name are not on file."""
    offer = view.get("person_offer", offer_id)
    if offer is None or offer.data["status"] != "offered":
        return None
    return next((o for o in waiting_offers_in(view) if o.id == offer_id), None)


def waiting_offers_in(view: Any) -> list[Any]:
    """The offers still waiting in a read of the records: those whose address and name are not on file."""
    addresses: set[str] = set()
    names: set[str] = set()
    for p in view.list("person"):
        addresses.update(v.lower() for v in all_values(p.data.get("how_to_reach")))
        names.update(n.lower() for n in [p.data["full_name"], *p.data.get("aliases", [])] if n)
    return [
        o
        for o in view.list("person_offer")
        if o.data["status"] == "offered"
        and o.data["address"].lower() not in addresses
        and o.data["name"].lower() not in names
    ]


def check_keep(ctx: Any, op: Any) -> list[str]:
    """The problems with keeping an offer, in plain words: it no longer waits (kept, left out, or the person is on file
    now)."""
    if find_waiting(ctx.store.read(), op.offer) is None:
        return ["That offer no longer stands: they are on file already, or it was answered."]
    if chosen := _placement(op):
        _, why = sides.person_write(ctx.store.read(), ctx.cfg, chosen)
        if why:
            return [why]
    return []


def _placement(op: Any) -> dict[str, Any]:
    """The sides the person chose for an offered person, as a write to a person's sides; empty when they chose none."""
    if op.sides:
        return {"sides": list(op.sides)}
    return {"side": op.side} if op.side else {}


def apply_keep(tx: Any, op: Any, ctx: Any, w: Any) -> list[dict[str, Any]]:
    """Add the person an offer names, as the person's own add: their name, the relation the offer gave, the sides of the
    accounts their mail came from (those the tally shows for the address; none when it shows none, which leaves the side
    not known) and their address as a way to reach them, and mark the offer kept with the person it became. One change,
    so Undo takes both back."""
    from engine import sides
    from engine.applier import contact_kind
    from engine.storage import StoreError

    offer = tx.get("person_offer", op.offer)
    if offer is None or offer.data["status"] != "offered":
        raise StoreError("That offer no longer stands.")
    address = offer.data["address"].lower()
    data: dict[str, Any] = {"full_name": offer.data["name"], "name_verified": True}
    if offer.data.get("relation"):
        data["relation"] = offer.data["relation"]
    chosen = _placement(op)
    if chosen:
        written, why = sides.person_write(ctx.store.read(), ctx.cfg, chosen)
        if why:
            raise StoreError(why)
        data |= written
    else:
        served = next((c.sides for c in contact_tally.tally(ctx.store, ctx.cfg) if c.address == address), ())
        if served:
            written, why = sides.person_write(ctx.store.read(), ctx.cfg, {"sides": list(served)})
            if why is None:
                data |= written
    kind = contact_kind(ctx.cfg, "email")
    if kind and "@" in address:
        data["how_to_reach"] = {kind: [address]}
    person = tx.create("person", data, w)
    tx.update("person_offer", offer.id, {"status": "kept", "person": person.id}, w, read_version=offer.version)
    return [{"kind": "person", "id": person.id}, {"kind": "person_offer", "id": offer.id}]


def keep(store: Any, cfg: Any, offer_id: str, sides: list[str] | None = None, side: str | None = None) -> str:
    """Keep an offer: the person is added and the offer settled, in one change the screen can undo, named for the
    person added. The sides are the ones the person chose, else those their mail came from. Returns the change's id;
    raises `StoreError` when the offer no longer stands."""
    from engine.applier import apply_as_person
    from engine.dispatcher import signal

    offer = store.read().get("person_offer", offer_id)
    op: dict[str, Any] = {"op": "person.keep_offer", "offer": offer_id}
    if sides:
        op["sides"] = sides
    elif side:
        op["side"] = side
    changeset = apply_as_person(
        store, cfg, [op], f"Added {offer.data['name']}" if offer is not None else "Added a person"
    )
    signal(store, "kept", [offer_id])
    return changeset


def dismiss(store: Any, cfg: Any, offer_id: str) -> str | None:
    """Leave an offer out ("Not this one"): it is never made again and a signal records it. Returns the change's id
    (Undo takes it back), or None when the offer no longer stood."""
    offer = store.read().get("person_offer", offer_id)
    return settle(store, cfg, offer.data["address"], "dismissed") if offer is not None else None


def held_for_go(store: Any) -> Any | None:
    """The look that waits for the person's go (its estimate is on it), or None. Today's go line and the People step
    both offer to start it."""
    for r in store.read().list("request"):
        if (
            r.data["task"] == TASK
            and r.data["state"] == "needs_you"
            and r.data.get("approval") == "required"
            and not r.data.get("dismissed")
        ):
            return r
    return None


def look_state(ws: Any, store: Any, cfg: Any, now: datetime | None = None) -> str:
    """Where the look stands, for the People step to say when it has no offer to show: `no_account` (no assistant is
    set up to do it), `waiting` (a look waits for the person's go), `working` (a look is queued or running), `not_yet`
    (the mail's first read, or the headers a look counts, are not in), `reading_more` (the rest of the year's headers
    is still being read: what was read so far gave no one, and the look goes again as more comes in), `looked` (a look
    ran on all there is and offered no one) or `too_little` (everything is read and it holds too little to look at,
    so no look ran: a look closed with no call is not a look)."""
    from engine.ai.smoke import ai_state

    requests = [r for r in store.read().list("request") if r.data["task"] == TASK and not r.data.get("dismissed")]
    if any(r.data["state"] == "needs_you" for r in requests):
        return "waiting"
    if any(r.data["state"] in ("queued", "running") for r in requests):
        return "working"
    if ai_state(ws, cfg, store)[0] != "ok":
        return "no_account"
    if not first_reads_in(store, cfg, now or datetime.now(UTC), ws) or not header_sample_in(store, cfg):
        return "not_yet"
    if more_mail_coming(store, cfg):
        return "reading_more"
    ran = any(
        r.data["state"] in ("done", "review") and r.data.get("waiting") not in (NOTHING_TO_LOOK_AT, SWITCHED_OFF)
        for r in requests
    )
    return "looked" if ran else "too_little"


def waiting_until(ws: Any, store: Any, cfg: Any, now: datetime) -> datetime | None:
    """When the mail the look waits for can be read again, when a first read or the first headers were asked to wait
    and the time has not come: the earliest such time; None when nothing waits for the service."""
    _, waiting = first_read_standing(store.read(), read_sources_of(store, cfg, ws), now)
    times = [until for _, until in waiting]
    for state in _sweeps(store.read(), cfg):
        at = _clock(state.get("at"), UTC) if int(state.get("taken", 0)) == 0 else None
        if at is not None and at > now:
            times.append(at)
    return min(times, default=None)


# ---- the packet ------------------------------------------------------------------------------------------------------


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date, sample: list[str] | None = None) -> Any:
    """The packet for one look. Stable first: the instructions, the op reference, the practice, what has been learned
    and the people on file. Then the request: the tally's lines and the repeating entries, marked as from outside."""
    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.names import PacketPeople
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _people, _task
    from engine.prompts import render

    contacts = tally_lines(store, cfg, req.id) if sample is None else sample
    series = series_lines(store, cfg) if sample is None else []
    if not contacts and not series:
        raise PacketRefused("there is nothing about who the person deals with to look at")
    habits = (
        []
        if _stand_in_lines is not None
        else mail_headers.habit_lines(store, cfg, {c.address for c, _ in shown_contacts(store, cfg, req.id)})
    )
    shown_tally = neutralize("\n".join(contacts)) if contacts else "(none)"
    shown_series = neutralize("\n".join(series)) if series else "(none)"
    shown_habits = neutralize("\n".join(habits)) if habits else "(none)"
    people = PacketPeople(store, cfg)
    learned = _learned(
        store,
        cfg,
        kind,
        people,
        projects=[],
        source=None,
        text=f"{shown_tally}\n{shown_series}\n{shown_habits}",
        today=today,
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
        f'# What the mail headers show (counts)\n<untrusted source="{HABITS_BLOCK}">\n{shown_habits}\n</untrusted>'
        if habits
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
        cites=f"{TASK}:{req.id}",
        data_level=_data_level(store, req.data),
        knowledge=learned.log,
    )


# ---- what it costs --------------------------------------------------------------------------------------------------

#: A line standing in for one entry of the tally while there is none yet (an invented, ordinary one), and how many such
#: entries a look shown nothing real is priced on.
_SAMPLE_LINE = "a.sender@example.com | A Sender | 6 from them, 3 to them | 2026-01-05 to 2026-01-26 | sides: none"
_SAMPLE_ENTRIES = 10


@dataclass(frozen=True)
class WeeklyCost:
    """What the look costs: `kind` is money (a priced account), runs (a plan: no money per run), unknown (an account
    with no known price) or none (no account takes the work). `per_look_usd` is one look and `per_week_usd` what
    the looks of a week add up to at the configured interval; `looks_a_week` is how many that is."""

    kind: str
    per_look_usd: float | None
    per_week_usd: float | None
    looks_a_week: float


def cost_of_a_week(ws: Any, store: Any, cfg: Any, router: Any, now: datetime | None = None) -> WeeklyCost:
    """About what the look costs a week, from the estimate for one look (its packet as built now, or for a sample of
    the tally's size while nothing is there yet) on the account it would use first, times the looks a week the
    configured interval makes."""
    from types import SimpleNamespace

    from engine.ai import pricing
    from engine.ai.calibration import estimate_tokens
    from engine.packet import PacketRefused

    now = now or datetime.now(UTC)
    today = now.astimezone(zone(cfg)).date()
    looks = 7 / cfg.dispatch.knowledge.person_look_every_days
    kind = store.plugins.task_kind(TASK)
    stand_in = SimpleNamespace(id="", data={})
    try:
        packet = build(ws, store, cfg, stand_in, kind, today)
    except PacketRefused:
        packet = build(ws, store, cfg, stand_in, kind, today, sample=[_SAMPLE_LINE] * min(_SAMPLE_ENTRIES, 50))
    level = _level(store, cfg)
    first = router.first_choice_for(TASK, level)
    if first is None:
        return WeeklyCost("none", None, None, looks)
    if pricing.is_flat(cfg, first.provider):
        return WeeklyCost("runs", None, None, looks)
    task = packet.task
    tokens = estimate_tokens(len(task.instructions) + len(task.stable) + len(task.request))
    price = router.estimate_for(TASK, tokens, data_level=level)
    if price is None:
        return WeeklyCost("unknown", None, None, looks)
    return WeeklyCost("money", price, price * looks, looks)
