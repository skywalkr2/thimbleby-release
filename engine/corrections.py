"""Asking for a change to something the assistant made (design 6.8, 6.20, 7.18).

The person types a note on the row of an action, a question, a decision, a calendar entry or a fact. It records one
correction signal naming the item, and the changeset and run that made it when there was one, and queues the usual
notes work about the item, whose packet carries the item as it stands now. What the assistant makes of the note is
reviewed and undone like any other work of its own.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.config import Config
from engine.intake import IntakeError, missed_note, note_as_input
from engine.storage import Store
from engine.workspace import Workspace

#: The kinds of item a change can be asked for, and the record kind each is. A decision is a question to the person.
CHANGEABLE: dict[str, str] = {
    "action": "action",
    "question": "question",
    "decision": "question",
    "event": "event",
    "fact": "fact",
}


def request_change(
    ws: Workspace, store: Store, cfg: Config, kind: str, record_id: str, note: str
) -> tuple[str | None, str]:
    """Record the correction and queue the work for the note. Returns the request made and the signal's id."""
    from engine.dispatcher import signal

    record_kind = CHANGEABLE.get(kind)
    if record_kind is None:
        raise IntakeError(f"A change can't be asked for on a {kind}.")
    if not note.strip():
        raise IntakeError("Say what to change.")
    view = store.read()
    if view.get(record_kind, record_id) is None:
        raise IntakeError(f"There is no {kind} {record_id}.")
    request = note_as_input(ws, store, cfg, item=(record_kind, record_id), text=note, route="change_requested")
    first: dict[str, Any] | None = next(iter(view.ledger(kind=record_kind, record_id=record_id)), None)
    made = first["changeset"] if first is not None else None
    signal_id = signal(store, "change_requested", [record_id], note=" ".join(note.split()), changeset=made)
    return request, signal_id


def missed_one(ws: Workspace, store: Store, cfg: Config, text: str, now: datetime | None = None) -> tuple[str, str]:
    """Record that the person said, in a plain sentence, what the assistant missed (design 6.32): their words go in as
    their own note marked as a miss, so the run adds what they name, and one `missed` signal counts it for the person
    and teaches at once. No record and no run is named, because the sentence is all the person knows. Returns the
    request made and the signal's id."""
    from engine.dispatcher import signal
    from engine.names import People

    words = " ".join(text.split())
    if not words:
        raise IntakeError("Say what the assistant missed.")
    request = missed_note(ws, store, cfg, text=text, now=now)
    signal_id = signal(store, "missed", [], note=words, now=now, person=People(store, cfg).pm)
    return request, signal_id


def answered_assistant(store: Store, cfg: Config, question_id: str, text: str) -> str | None:
    """Record that the person wrote an answer to a question the assistant asked them, so the assistant learns from it at
    once. The signal names the question, and the changeset and run that made it when there was one. However short the
    answer, the assistant reads it and decides whether it teaches anything; only an empty answer records nothing.
    Returns the signal's id."""
    from engine.dispatcher import signal

    words = " ".join(text.split())
    if not words:
        return None
    first: dict[str, Any] | None = next(iter(store.read().ledger(kind="question", record_id=question_id)), None)
    made = first["changeset"] if first is not None else None
    return signal(store, "answered_assistant", [question_id], note=words, changeset=made)


def redo_items(store: Store, request: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
    """The records the earlier work of a request that redoes sent-back work touched, each with the statuses its ops
    ended in (applied, undone, held, ...). Empty when the request redoes nothing or the earlier request made no
    changeset. Reads only."""
    previous = request.get("previous")
    view = store.read()
    old = view.get("request", previous) if previous else None
    changeset = view.get("changeset", old.data["changeset"]) if old is not None and old.data.get("changeset") else None
    found: dict[tuple[str, str], set[str]] = {}
    if changeset is None:
        return found
    for outcome in changeset.data["ops"]:
        for record in outcome.get("records") or []:
            found.setdefault((record["kind"], record["id"]), set()).add(outcome["status"])
    return found


#: How many words in a row of an item's name a report must repeat to count as naming it (a shorter name, all of it).
NAME_WINDOW = 4


def report_names_item(store: Store, request: dict[str, Any], text: str) -> bool:
    """Whether a report drafted while redoing sent-back work says what the data shows: it names at least one item the
    earlier work touched, by the words the person reads (its label or title; a run of its words when it is long). A
    request that redoes nothing, or whose earlier work touched nothing, has nothing to name, so the report passes."""
    items = redo_items(store, request)
    if not items:
        return True
    view = store.read()
    names: list[str] = []
    old = view.get("request", request["previous"])
    changeset = view.get("changeset", old.data["changeset"])
    for o in changeset.data["ops"]:
        # An item taken back is gone from the store, so its words are the ones the earlier work gave it.
        names += [str(o.get("label") or "")] + [
            str((o.get("op") or {}).get(k) or "") for k in ("title", "text", "name")
        ]
    for kind, record_id in items:
        record = view.get(kind, record_id)
        if record is not None:
            names += [str(record.data.get(k) or "") for k in ("title", "name", "full_name", "text")]
    spoken = " ".join(text.casefold().split())
    for name in names:
        words = name.casefold().split()
        windows = (
            [words]
            if len(words) <= NAME_WINDOW
            else [words[i : i + NAME_WINDOW] for i in range(len(words) - NAME_WINDOW + 1)]
        )
        if words and any(" ".join(w) in spoken for w in windows):
            return True
    return False
