"""The one question a meeting the person runs can need before it starts (design 6.32, "Meetings the person adds,
prepared like calendar entries"): it has no agenda by the time its prep opens, or someone it needs is away that day.

It is asked of the person, once for each date of the meeting, in any state it ends in; a meeting the person only attends
gets none. Rules find both cases, with no AI: the agenda is what the entry holds, and a person is away by the same read
of days off the rest of the app uses (`engine.days_off`). Both reasons together are one question."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine import days_off
from engine.meeting_prep import hand_made, prep_lines
from engine.names import People
from engine.sides import word
from engine.storage import StoreError, WriteContext
from engine.today import zone

KIND = "meeting_ready"
_ENGINE = WriteContext(actor="engine", trust="trusted", op="meeting.ask")


def _asked(view: Any) -> set[tuple[str, str]]:
    """The meeting dates already asked about, in any state: an entry's id and the date its rule had."""
    return {
        (r["event"], r["date"])
        for q in view.list("question")
        if (r := q.data.get("resolves") or {}).get("kind") == KIND
    }


def ask(store: Any, cfg: Any, now: datetime) -> list[str]:
    """Ask the question for each date of a meeting the person runs whose prep is open and that has no agenda or needs
    someone who is away. Returns the ids of the questions made (none when every date was asked before)."""
    view = store.read()
    pm = cfg.workspace.user.person
    if not pm:
        return []
    here = zone(cfg)
    people = People(store, cfg)
    done = _asked(view)
    made: list[dict[str, Any]] = []
    for line in prep_lines(store, cfg, now):
        entry = view.get("event", line.event)
        if entry is None or not hand_made(entry.data) or entry.data.get("role") != "run":
            continue
        date_key = line.occurrence or line.start.isoformat()
        if (line.event, date_key) in done:
            continue
        day = line.start.astimezone(here).date()
        away = [
            said
            for person in line.people
            if (said := days_off.off_on(view, cfg, person, day, people.name(person))) is not None
        ]
        if not line.no_agenda and not away:
            continue
        shown = day.strftime("%a %b ") + str(day.day)
        text = " ".join(
            [
                *([word(cfg, "meeting_ask.no_agenda")] if line.no_agenda else []),
                *(word(cfg, "meeting_ask.away").format(why=w) for w in away),
            ]
        )
        made.append(
            {
                "to": pm,
                "title": word(cfg, "meeting_ask.title").format(title=line.title, day=shown),
                "text": text,
                "kind": "question",
                "event": line.event,
                "matters_for": word(cfg, "meeting_ask.matters").format(title=line.title, day=shown),
                "resolves": {
                    "kind": KIND,
                    "event": line.event,
                    "date": date_key,
                    "agenda": line.no_agenda,
                    "away": bool(away),
                },
            }
        )
    if not made:
        return []
    ids: list[str] = []
    try:
        with store.transaction() as tx:
            for data in made:
                ids.append(tx.create("question", data, _ENGINE).id)
    except StoreError:
        return []
    return ids
