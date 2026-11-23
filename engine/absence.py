"""Who is away, read from an absence calendar by rules (design 5.1 "Away periods from an absence calendar").

A calendar source with `holds: absence` keeps no calendar entries and hands nothing to the assistant. Each entry it
lists is read into one period on the person's `away` list, with no AI run:

- **Who:** a name in the entry's title (a full name, an alias, or a first name with the last name's initial), else the
  one person asked, else the organizer, each resolved to a person the workspace knows. One person: the period is
  written. Several: one question per entry series asks which. Nobody known: nothing is written and nothing is asked; the
  name is counted so the source's row can offer "Add as a person".
- **What is kept:** the first and last day (an all-day entry's end is exclusive; a timed entry counts its days whole), a
  label only when the title holds one of the workspace's away words, and the source and entry it came from. No other
  word of the entry is kept.
- **Moves followed:** a later read moves or removes the same period. An entry outside the read's window is not treated
  as gone. A period the person has edited, or removed, is theirs and no read changes it.

The periods are written as one change with Undo (`away.read`, applied by `apply_for_absence`)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine.connectors import EventPerson, SourceItem, moment
from engine.language_words import language_words
from engine.local_day import day_of, zone_of
from engine.sides import word as wording
from engine.storage import StoreError, WriteContext

log = logging.getLogger(__name__)

KIND = "away"
SUMMARY = "Read who is away from {source}"
#: The words around a name in a title that are not part of it ("Ana is on vacation").
_FILLER = frozenset({"is", "are", "on", "in", "at", "the", "out", "of", "for", "from", "until", "till", "to", "and"})
_ENGINE = WriteContext(actor="absence", trust="untrusted", op="away.ask")
_MAX_NAME = 60
_MAX_NAMES = 50


@dataclass
class Entry:
    """One entry of an absence calendar, as the rules read it."""

    key: str
    series: str
    title: str
    start: date
    end: date | None  # the last day, None for a single day
    gone: bool
    organizer: EventPerson | None
    attendees: tuple[EventPerson, ...]


@dataclass
class Report:
    written: int = 0  # periods added, moved or removed
    asked: int = 0  # questions asked about which person
    names: list[str] = field(default_factory=list)  # names that matched nobody, for "Add as a person"
    changeset: str | None = None


# ---- reading the entries ------------------------------------------------------------------------------------------


def _days(details: Any, start: str, end: str | None, here: Any = UTC) -> tuple[date, date | None] | None:
    """The first day and the last day (None for one day) of a date of an entry; None when the times can't be read."""
    try:
        if details.all_day:
            first = moment(start, all_day=True)
            last = moment(end, all_day=True) - timedelta(days=1) if end else first
        else:
            # The days are the person's own: both ends go into their zone before the day or the midnight is read.
            begins = moment(start).astimezone(here)
            ends = moment(end).astimezone(here) if end else begins
            first, last = begins.date(), ends.date()
            if end and ends > begins and ends.time() == datetime.min.time().replace(tzinfo=None):
                last = last - timedelta(days=1)  # an entry that ends at midnight does not take the next day
        if last < first:
            return None
        return first, (last if last > first else None)
    except (TypeError, ValueError):
        return None


def entries_of(items: list[SourceItem], here: Any = UTC) -> list[Entry]:
    """The entries a read lists, one for each date of a repeating one."""
    found: list[Entry] = []
    for item in items:
        details = item.event
        if details is None:
            continue
        dates = list(details.occurrences) if details.repeats and details.occurrences else [None]
        for each in dates:
            start, end = (each.start, each.end) if each is not None else (details.start, details.end)
            days = _days(details, start, end, here)
            if days is None:
                continue
            key = f"{item.key}#{each.was or each.start}" if each is not None else item.key
            title = ((each.title if each is not None else None) or item.title or "").strip()
            gone = bool(each.cancelled if each is not None else details.cancelled)
            found.append(Entry(key, item.key, title, days[0], days[1], gone, details.organizer, details.attendees))
    return found


# ---- who ----------------------------------------------------------------------------------------------------------


def _words(text: str, words: list[str]) -> re.Pattern[str] | None:
    wanted = sorted({w.strip() for w in words if w.strip()}, key=len, reverse=True)
    if not wanted:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in wanted) + r")(?!\w)", re.IGNORECASE)


def label_of(title: str, away_words: list[str]) -> str | None:
    """The first of the workspace's away words the title holds, as the workspace writes it; the rest of the title is
    never kept."""
    for word in away_words:
        if word.strip() and re.search(rf"(?<!\w){re.escape(word.strip())}(?!\w)", title, re.IGNORECASE):
            return word.strip()[:80]
    return None


def named_in(title: str, records: dict[str, Any]) -> set[str]:
    """The people whose full name or alias the title holds as whole words, or whose first name is followed by the
    initial of their last name ("Ana K."). A first name alone is nobody: two people may share it."""
    found: set[str] = set()
    for pid, data in records.items():
        names = [data["full_name"], *data.get("aliases", [])]
        if any(n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", title, re.IGNORECASE) for n in names):
            found.add(pid)
            continue
        parts = data["full_name"].replace(".", " ").split()
        if len(parts) >= 2:
            firsts = {parts[0], (data.get("first_name") or "").strip()} - {""}
            initial = parts[-1][0]
            for first in firsts:
                if re.search(rf"(?<!\w){re.escape(first)}\s+{re.escape(initial)}\.?(?!\w)", title, re.IGNORECASE):
                    found.add(pid)
    return found


def _resolve(people: Any, who: EventPerson | None) -> str | None:
    if who is None:
        return None
    label = f"{who.name} <{who.address}>" if who.name and who.address else who.address or who.name or ""
    found = people.match_entries([label]) if label else set()
    return next(iter(found)) if len(found) == 1 else None


def who_is_it(entry: Entry, people: Any) -> set[str]:
    """The people an entry names, by the rules: those its title names, else the one person asked, else the organizer
    (several people asked, with no organizer known, are several)."""
    in_title = named_in(entry.title, people.records)
    if in_title:
        return in_title
    asked = {p for p in (_resolve(people, a) for a in entry.attendees) if p}
    organizer = _resolve(people, entry.organizer)
    if len(asked) == 1:
        return asked
    if organizer:
        return {organizer}
    return asked


def unknown_name(entry: Entry, away_words: list[str]) -> str | None:
    """The name an entry gives that no known person has: its title without the away words and the little words around a
    name, else the organizer's or an attendee's name. None when it gives none."""
    pattern = _words(entry.title, away_words)
    text = pattern.sub(" ", entry.title) if pattern else entry.title
    words = [w for w in re.sub(r"[-–—:()\[\],;/|]", " ", text).split()]
    while words and words[0].casefold().strip("'’s") in _FILLER:
        words.pop(0)
    while words and words[-1].casefold().strip("'’s") in _FILLER:
        words.pop()
    name = " ".join(words).strip()
    if name and len(name) <= _MAX_NAME:
        return name
    for who in (entry.organizer, *entry.attendees):
        if who is not None and who.name and len(who.name.strip()) <= _MAX_NAME:
            return who.name.strip()
    return None


# ---- the periods already written ----------------------------------------------------------------------------------


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def held_periods(view: Any, source: str) -> dict[str, tuple[str, dict[str, Any]]]:
    """The periods this source's entries made, by entry key: the person they are on and the period."""
    held: dict[str, tuple[str, dict[str, Any]]] = {}
    for person in view.list("person"):
        for period in person.data.get("away") or []:
            read = period.get("read") or {}
            if read.get("source") == source:
                held[read["entry"]] = (person.id, period)
    return held


def edited(period: dict[str, Any]) -> bool:
    """Whether the person changed a period that was read from an entry: its days or label differ from what was read."""
    read = period.get("read") or {}
    return (str(period["start"]), period.get("end") and str(period["end"]), period.get("label")) != (
        str(read["start"]),
        read.get("end") and str(read["end"]),
        read.get("label"),
    )


def removed_by_person(view: Any, person: str, source: str, entry: str) -> bool:
    """Whether a period this entry made was taken off the person's list by anyone but a read of the calendar (the
    person's own edit, or Undo): it is then theirs, and the entry doesn't make it again."""
    present, by_read, ever = False, False, False
    for line in view.ledger(kind="person", record_id=person, fields=["away"]):
        now = any(
            (p.get("read") or {}).get("source") == source and (p.get("read") or {}).get("entry") == entry
            for p in line.get("after") or []
        )
        if present and not now:
            by_read = line.get("op") == "away.read"
        ever, present = ever or now, now
    return ever and not present and not by_read


def apply(tx: Any, op: Any, w: WriteContext) -> bool:
    """Add, move or remove the period one entry made, on the person's record. A period the person has edited is left as
    it is, and so is one the person already has for the same days. Returns whether the record changed."""
    found = tx.get("person", op.person)
    if found is None:
        raise StoreError(f"there is no person {op.person}")
    away = list(found.data.get("away") or [])
    here = next(
        (
            i
            for i, p in enumerate(away)
            if (p.get("read") or {}).get("source") == op.source and (p.get("read") or {}).get("entry") == op.entry
        ),
        None,
    )
    days = {"start": op.start.isoformat(), "end": _iso(op.end), "label": op.label}
    if here is None:
        if op.gone or any((p["start"], p.get("end")) == (days["start"], days["end"]) for p in away):
            return False
        read = {"source": op.source, "entry": op.entry, "series": op.series, **days}
        away.append({**days, "read": read})
    else:
        period = away[here]
        if edited(period):
            return False
        if op.gone:
            del away[here]
        elif (period["start"], period.get("end"), period.get("label")) == (days["start"], days["end"], days["label"]):
            return False
        else:
            away[here] = {**days, "read": {**period["read"], **days}}
    tx.update("person", op.person, {"away": away}, w, read_version=found.version)
    return True


# ---- the read -----------------------------------------------------------------------------------------------------


def window_of(settings: Any, now: datetime, here: Any = UTC) -> tuple[date, date] | None:
    """The days a read of this calendar looks at, when its settings say (`days_back`, `days_ahead`); None otherwise."""
    back, ahead = getattr(settings, "days_back", None), getattr(settings, "days_ahead", None)
    if not isinstance(back, int) or not isinstance(ahead, int):
        return None
    today = now.astimezone(here).date()
    return today - timedelta(days=back), today + timedelta(days=ahead)


def read(
    store: Any,
    cfg: Any,
    source: Any,
    poll: Any,
    settings: Any,
    now: datetime,
) -> Report:
    """Read an absence calendar's entries into the days people are away. Never raises: a read that can't be written
    leaves the periods as they were. Returns what was done, with the names that matched nobody."""
    from engine.applier import apply_for_absence
    from engine.names import People

    report = Report()
    view = store.read()
    people = People(store, cfg)
    away_words = list(language_words(cfg.language, "away_words"))
    here = zone_of(cfg)
    entries = entries_of(poll.items, here)
    held = held_periods(view, source.id)
    window = window_of(settings, now, here)
    asked = _asked(view, source.id)
    pm = cfg.workspace.user.person
    ops: list[dict[str, Any]] = []
    questions: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    listed = set()
    for entry in entries:
        listed.add(entry.key)
        label = label_of(entry.title, away_words)
        days = {"start": entry.start, "end": entry.end, "label": label}
        if entry.key in held:
            person = held[entry.key][0]
        else:
            if entry.gone:
                continue
            person = _answered(view, asked, entry.series, people)
            if person is None:
                found = who_is_it(entry, people)
                if not found:
                    name = unknown_name(entry, away_words)
                    if name:
                        names.setdefault(name.casefold(), name)
                    continue
                if len(found) > 1:
                    if entry.series not in asked and pm and view.get("person", pm) is not None:
                        ask = questions.setdefault(entry.series, {"people": sorted(found), "entries": []})
                        ask["entries"].append(
                            {"entry": entry.key, "start": entry.start.isoformat(), **_end(entry), "label": label}
                        )
                    continue
                person = next(iter(found))
            if removed_by_person(view, person, source.id, entry.key):
                continue
        ops.append(_op(person, source.id, entry, days, gone=entry.gone))
    for key, (person, period) in held.items():
        if key in listed or edited(period):
            continue
        if _gone_for_sure(period, key, poll, window):
            read_period = period["read"]
            ops.append(
                {
                    "op": "away.read",
                    "person": person,
                    "source": source.id,
                    "entry": key,
                    "series": read_period.get("series"),
                    "start": str(period["start"]),
                    "end": period.get("end"),
                    "label": period.get("label"),
                    "gone": True,
                }
            )
    ops = [o for o in ops if _changes(o, held)]
    report.names = list(names.values())[:_MAX_NAMES]
    if ops:
        try:
            label_text = source.label or source.id
            report.changeset = apply_for_absence(store, cfg, ops, SUMMARY.format(source=label_text))
            report.written = len(ops)
        except StoreError as err:
            log.warning("The days away in %s couldn't be kept: %s", source.id, err)
    if questions:
        report.asked = _ask(store, cfg, source, questions, people)
    return report


def _end(entry: Entry) -> dict[str, Any]:
    return {"end": entry.end.isoformat() if entry.end else None}


def _op(person: str, source: str, entry: Entry, days: dict[str, Any], *, gone: bool) -> dict[str, Any]:
    return {
        "op": "away.read",
        "person": person,
        "source": source,
        "entry": entry.key,
        "series": entry.series,
        "start": days["start"].isoformat(),
        "end": _iso(days["end"]),
        "label": days["label"],
        "gone": gone,
    }


def _changes(op: dict[str, Any], held: dict[str, tuple[str, dict[str, Any]]]) -> bool:
    """Whether an op would change anything, so a read that finds nothing new writes no change."""
    have = held.get(op["entry"])
    if have is None:
        return not op["gone"]
    period = have[1]
    if edited(period):
        return False
    if op["gone"]:
        return True
    return (str(period["start"]), period.get("end") and str(period["end"]), period.get("label")) != (
        op["start"],
        op["end"],
        op["label"],
    )


def _gone_for_sure(period: dict[str, Any], key: str, poll: Any, window: tuple[date, date] | None) -> bool:
    """Whether an entry missing from a read is gone: the service said so, or the read lists everything, or the read's
    window covers every day of the period (an entry outside the window is not treated as gone)."""
    series = (period.get("read") or {}).get("series") or key
    if key in poll.removed or series in poll.removed:
        return True
    if poll.complete:
        return True
    if window is None:
        return False
    first = day_of(period["start"], UTC)
    last = day_of(period.get("end") or period["start"], UTC)
    return window[0] <= first and last <= window[1]


# ---- asking which person ------------------------------------------------------------------------------------------


def _asked(view: Any, source: str) -> dict[str, Any]:
    """The questions about which person an entry series is for that were asked for this source, by series, of any
    state: a series is asked about once."""
    return {
        q.data["resolves"]["series"]: q
        for q in view.list("question")
        if (q.data.get("resolves") or {}).get("kind") == KIND and q.data["resolves"].get("source") == source
    }


def _answered(view: Any, asked: dict[str, Any], series: str, people: Any) -> str | None:
    """The person the person chose for a series, when it was answered and they are still known."""
    question = asked.get(series)
    if question is None or question.data["status"] != "answered":
        return None
    chosen = question.data.get("answer")
    return chosen if chosen in people.records else None


def _ask(store: Any, cfg: Any, source: Any, questions: dict[str, dict[str, Any]], people: Any) -> int:
    pm = cfg.workspace.user.person
    count = 0
    try:
        with store.transaction() as tx:
            for series, ask in questions.items():
                names = ", ".join(people.name(p) for p in ask["people"])
                first = ask["entries"][0]
                days = first["start"] if not first.get("end") else f"{first['start']} to {first['end']}"
                tx.create(
                    "question",
                    {
                        "to": pm,
                        "title": wording(cfg, "absence_ask.title").format(source=source.label or source.id),
                        "text": wording(cfg, "absence_ask.text").format(days=days, names=names),
                        "kind": "decision",
                        "options": ask["people"],
                        "resolves": {"kind": KIND, "source": source.id, "series": series, "entries": ask["entries"]},
                    },
                    _ENGINE,
                )
                count += 1
    except StoreError as err:
        log.warning("The question about days away in %s couldn't be asked: %s", source.id, err)
        return 0
    return count


def answer(store: Any, cfg: Any, question_id: str, person: str) -> str | None:
    """The person's answer to which person an entry series is for: the periods of the series' entries are written for
    them (one change with Undo), and the question is answered. Returns the change's id, or None when nothing needed
    writing. Refuses a person the question didn't offer."""
    from engine.applier import apply_for_absence

    question = store.read().get("question", question_id)
    resolves = (question.data.get("resolves") or {}) if question is not None else {}
    if question is None or resolves.get("kind") != KIND:
        raise StoreError("That isn't a question about whose days away these are.")
    if person not in (question.data.get("options") or []):
        raise StoreError("Choose one of the people listed.")
    ops = [
        {
            "op": "away.read",
            "person": person,
            "source": resolves["source"],
            "entry": e["entry"],
            "series": resolves["series"],
            "start": e["start"],
            "end": e.get("end"),
            "label": e.get("label"),
            "gone": False,
        }
        for e in resolves["entries"]
    ]
    changeset = apply_for_absence(store, cfg, ops, SUMMARY.format(source=resolves["source"])) if ops else None
    with store.transaction() as tx:
        current = tx.get("question", question_id)
        tx.update(
            "question",
            question_id,
            {"status": "answered", "answer": person},
            WriteContext(actor="pm", trust="trusted", op="away.answer"),
            read_version=current.version,
        )
    return changeset
