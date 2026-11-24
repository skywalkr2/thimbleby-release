"""A workspace with about three months of made-up history, for measuring what a run costs once a workspace has grown.

Every name is made up; addresses use example.com. `age` adds to a workspace made from a demo: people, projects, to-dos
(most of them done), questions (most of them closed), standing lessons, glossary terms, facts, calendar entries and the
pasted mail a person hands in over the weeks. The amounts are one busy person's three months, not a worst case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine.intake import hand_in
from engine.storage import Store, WriteContext

WHEN = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
_CTX = WriteContext(actor="pm", trust="trusted", op="aged.history")

_FIRST = ["Avo", "Brem", "Cael", "Dovi", "Esk", "Fenn", "Gael", "Hesk", "Iro", "Jova", "Kes", "Lio", "Mav", "Nolu"]
_LAST = [
    "Alder",
    "Birch",
    "Cobbe",
    "Dunmar",
    "Ellor",
    "Fenmoor",
    "Garrow",
    "Halden",
    "Ivers",
    "Jarrel",
    "Kemble",
    "Lorne",
]
_THING = [
    "the vendor contract",
    "the seating plan",
    "the budget sheet",
    "the onboarding checklist",
    "the training deck",
    "the supplier audit",
    "the travel booking",
    "the quarterly summary",
    "the press list",
    "the venue walk-through",
]
_VERB = ["Send", "Review", "Confirm", "Update", "Draft", "Book", "Chase", "File", "Check", "Share"]
_TERMS = ["kiosk", "tranche", "runbook", "burn-down", "sign-off", "stand-in", "hand-off", "cut-over", "dry run"]


@dataclass(frozen=True)
class Amounts:
    people: int = 60
    projects: int = 12
    actions_open: int = 90
    actions_done: int = 260
    questions_open: int = 25
    questions_closed: int = 120
    lessons: int = 70
    glossary: int = 120
    facts: int = 400
    events: int = 40
    mails: int = 40


def _name(i: int) -> str:
    return f"{_FIRST[i % len(_FIRST)]} {_LAST[(i * 7 + i // len(_FIRST)) % len(_LAST)]}{i}"


TODAY = WHEN.date()
BUSY = Amounts()


def age(ws: Any, store: Store, cfg: Any, amounts: Amounts = BUSY, today: date = TODAY) -> None:
    """Add the history to the workspace's store; call before building a packet."""
    stamp = WHEN.isoformat()
    people: list[str] = []
    projects: list[str] = []
    with store.transaction() as tx:
        for i in range(amounts.people):
            made = tx.create(
                "person",
                {
                    "full_name": _name(i),
                    "aliases": [_FIRST[i % len(_FIRST)]],
                    "role": f"Lead for {_THING[i % len(_THING)]}",
                    "why_they_matter": f"Holds the answers about {_THING[(i + 3) % len(_THING)]}.",
                    "how_to_reach": {"email": [f"person{i}@example.com"]},
                },
                _CTX,
            )
            people.append(made.id)
        for i in range(amounts.projects):
            made = tx.create(
                "project",
                {
                    "name": f"Piece of work {i} for {_THING[i % len(_THING)]}",
                    "summary": f"Keeps {_THING[i % len(_THING)]} moving until the end of the quarter.",
                    "aliases": [f"POW{i}"],
                },
                _CTX,
            )
            projects.append(made.id)
        for i in range(amounts.actions_open + amounts.actions_done):
            done = i >= amounts.actions_open
            tx.create(
                "action",
                {
                    "text": f"{_VERB[i % len(_VERB)]} {_THING[i % len(_THING)]} for week {i % 13}",
                    "project": projects[i % len(projects)],
                    "owners": [{"person": people[i % len(people)]}],
                    "due": (today + timedelta(days=(i % 40) - 20)).isoformat(),
                    **({"status": "done"} if done else {}),
                },
                _CTX,
            )
        for i in range(amounts.questions_open + amounts.questions_closed):
            closed = i >= amounts.questions_open
            tx.create(
                "question",
                {
                    "to": people[i % len(people)],
                    "title": f"Is {_THING[i % len(_THING)]} ready for week {i % 13}?",
                    "text": (f"Last week's note said {_THING[(i + 1) % len(_THING)]} was waiting on a reply. " * 6)[
                        :380
                    ],
                    "projects": [projects[i % len(projects)]],
                    **({"status": "answered", "answer": "Yes, it went out on Friday."} if closed else {}),
                },
                _CTX,
            )
        for i in range(amounts.lessons):
            tx.create(
                "lesson",
                {
                    "text": f"When {_THING[i % len(_THING)]} comes up in a message from {_name(i)}, the date in it is "
                    f"the day it is needed, not the day it was sent; ask before moving anything (case {i}).",
                    "origin": "person",
                    "status": "active",
                    "kept_by": people[0],
                    "kept_at": stamp,
                    "learned_at": stamp,
                },
                _CTX,
            )
        for i in range(amounts.glossary):
            tx.create(
                "glossary_entry",
                {
                    "term": f"{_TERMS[i % len(_TERMS)]}-{i}",
                    "meaning": f"The step in {_THING[i % len(_THING)]} that comes before the next review.",
                    "text": f"{_TERMS[i % len(_TERMS)]}-{i}: the step in {_THING[i % len(_THING)]} before a review.",
                    "origin": "person",
                    "status": "active",
                    "kept_by": people[0],
                    "kept_at": stamp,
                    "learned_at": stamp,
                },
                _CTX,
            )
        for i in range(amounts.facts):
            tx.create(
                "fact",
                {
                    "text": f"{_THING[i % len(_THING)].capitalize()} for piece {i % amounts.projects} is due in week "
                    f"{i % 13}.",
                    "project": projects[i % len(projects)],
                },
                _CTX,
            )
        for i in range(amounts.events):
            tx.create(
                "event",
                {
                    "title": f"Review of {_THING[i % len(_THING)]}",
                    "start": (today + timedelta(days=i + 1)).isoformat() + "T10:00:00+00:00",
                    "project": projects[i % len(projects)],
                },
                _CTX,
            )
    for i in range(amounts.mails):
        hand_in(
            ws,
            store,
            pasted=f"Hello, the update on {_THING[i % len(_THING)]} is due soon, please confirm (message {i}).",
            now=WHEN + timedelta(minutes=i),
        )


def everyday_requests(ws: Any, store: Store, cfg: Any, now: datetime = WHEN) -> dict[str, str]:
    """One queued request for each everyday kind of work that can be made without an outside service: a pasted note,
    a question about a record, the work behind a to-do, a prep note for a calendar entry and the reading of the week.
    Returns the request id by task kind."""
    from engine import action_work, conversation, meeting_prep, week_ahead

    view = store.read()
    action = next(a.id for a in view.list("action") if a.data["status"] == "open")
    entry = next(e.id for e in view.list("event"))
    made = {
        "notes": hand_in(ws, store, pasted="Please confirm the printer proof moves to the 16th.", now=now).request,
        "ask": conversation.say(store, "action", action, "What is waiting on whom?"),
        "action-work": action_work.hand_over(store, action),
        "meeting-prep": meeting_prep.ask_for_note(store, entry),
        "week-ahead": week_ahead.read_again(store, cfg, now),
    }
    return made


def packet_tokens(ws: Any, store: Store, cfg: Any, requests: dict[str, str], today: date = TODAY) -> dict[str, int]:
    """What each request's packet comes to, in tokens by the app's own count (the count every estimate starts from)."""
    from engine import packet
    from engine.ai.calibration import estimate_tokens

    return {
        kind: estimate_tokens(packet.build(ws, store, cfg, request, today).task.size)
        for kind, request in requests.items()
    }
