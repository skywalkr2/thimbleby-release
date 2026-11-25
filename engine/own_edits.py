"""The person's own edits of one item, folded into one row of What changed (design 7.13).

An edit the person makes on screen is a change of its own, so editing one item five times in a day would list five rows.
They are one row instead ("You changed Pay the deposit 5 times") that opens to the list of edits. Only the person's own
edits fold: a change the assistant made, and anything made from an input, stays a row of its own each. Two days are two
rows, the day being the person's own.

The people the person takes from those the assistant offered fold the same way into one row of the day ("You added 12
people"), each still a change of its own with its own Undo.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

#: The ops that change something already there (an edit); one that adds, answers or ends an item is not an edit of it.
EDIT_OPS = frozenset(
    {
        "record.edit",
        "record.set",
        "event.set",
        "action.move",
        "action.hold",
        "action.unhold",
        "action.owners",
        "action.part",
        "action.repeat",
        "question.update",
        "question.move",
        "person.stance",
        "text.edit",
    }
)


def edited_record(request: Mapping[str, Any], changeset: Mapping[str, Any] | None) -> tuple[str, str] | None:
    """The one record a person's own on-screen edit changed: (kind, id), or None when the change is not such an edit
    (the assistant's, made from an input, adding or answering something, or touching more than one record)."""
    if request.get("origin") != "pm" or request.get("source") or request.get("state") != "done" or changeset is None:
        return None
    ops = changeset.get("ops") or []
    found: set[tuple[str, str]] = set()
    for outcome in ops:
        refs = outcome.get("records") or []
        if outcome["op"]["op"] not in EDIT_OPS or not refs:
            return None
        found |= {(ref["kind"], ref["id"]) for ref in refs}
    return next(iter(found)) if len(found) == 1 else None


#: The group a person's own taking of offered people folds under in one day: not one record, but all the people added.
ADDED_PEOPLE = ("added", "people")


def added_a_person(request: Mapping[str, Any], changeset: Mapping[str, Any] | None) -> bool:
    """Whether a change is the person's own taking of one person the assistant offered (the one op that adds them and
    answers the offer, or the offer's answer alone when they were added another way)."""
    if request.get("origin") != "pm" or request.get("source") or request.get("state") != "done" or changeset is None:
        return False
    ops = changeset.get("ops") or []
    if len(ops) != 1:
        return False
    op = ops[0]["op"]
    if op["op"] == "person.keep_offer":
        return True
    return (
        op["op"] == "record.edit"
        and (op.get("record") or {}).get("kind") == "person_offer"
        and (op.get("fields") or {}).get("status") == "kept"
    )


def day_of(created_at: str, zone: Any) -> date:
    """The day a change was made, on the person's own clock."""
    return datetime.fromisoformat(created_at).astimezone(zone).date()
