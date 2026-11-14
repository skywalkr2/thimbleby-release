"""Forgetting a person (design 5.2, 12.4; S-0443 part 1): a recorded redaction of the person's own record.

The record stays, with its id, so every reference by id still holds. Its values are replaced by a marker, the ledger
gives up their earlier values, the earlier changes that quote them are scrubbed, and the readable export's history is
rebuilt as a fresh one. Nothing here brings a value back: an Undo of an earlier change to the person is refused
(`engine/redactions.py`). What else holds the person (their mail's text, the knowledge and the records that mention
them, evaluation cases) is reached by the same change (`engine/forget_reach.py`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.storage import Store, StoreError, WriteContext
from engine.storage.store import Tx

#: The name every forgotten person shows under; the screen says when they were forgotten.
FORGOTTEN_NAME = "Forgotten person"
#: The person's own values the forget blanks, each to its empty state. `full_name` takes the marker instead. The
#: registry of redacting ops (`engine/redactions.py`) reads this list, so the ledger gives up the same fields.
BLANKED: dict[str, Any] = {
    "first_name": None,
    "aliases": [],
    "role": None,
    "how_to_reach": {},
    "why_they_matter": None,
    "relation": None,
    "away": [],
    "ext": {},
}
FORGET_FIELDS = ["full_name", *BLANKED]
#: What of an earlier change the same redaction reaches: the values its ops set and the words that name the person.
CHANGESET_FIELDS = ["ops", "summary", "topic"]
#: The field of a request that holds the summary of the change it answered, which the same redaction reaches.
REQUEST_FIELDS = ["note"]
#: The parts of an op that only say which record it is about; the rest of a touched change's op is blanked.
_OP_KEEPS = ("op", "record", "id", "person", "kind", "field", "read_version")


def forgotten_problem(view: Any, kind: str, record_id: str) -> str | None:
    """Why a change to this record is refused because the person was forgotten, or None."""
    if kind != "person":
        return None
    held = view.get("person", record_id)
    if held is not None and held.data.get("forgotten_on"):
        return f"person {record_id} was forgotten; their record can't be changed"
    return None


def forget_record(
    tx: Tx, person_id: str, ctx: WriteContext, *, read_version: int, today: str, store: Any, root: Path
) -> None:
    """Forget a person inside the applier's transaction: the record's values are blanked and marked forgotten, the
    ledger gives up their earlier values, every earlier change that quotes them is scrubbed, and everything else that
    holds them is reached (`engine/forget_reach.py`). Refused when they were forgotten already."""
    from engine import forget_reach

    held = tx.get("person", person_id)
    if held is None:
        raise StoreError(f"there is no person {person_id}")
    if held.data.get("forgotten_on"):
        raise StoreError(f"person {person_id} was forgotten already")
    plan = forget_reach.plan_of(tx, person_id, root)
    names = plan.ids
    # Every ledger entry the forget gives up also loses its evidence quote.
    tx.blank_evidence = True
    tx.update(
        "person",
        person_id,
        {**BLANKED, "full_name": FORGOTTEN_NAME, "forgotten_on": today, "name_verified": True},
        ctx,
        read_version=read_version,
    )
    tx.redact_ledger("person", person_id, FORGET_FIELDS)
    for cs in tx.list("changeset"):
        scrubbed = _scrub_changeset(cs.data, person_id, names)
        if scrubbed:
            tx.update("changeset", cs.id, scrubbed, ctx, read_version=cs.version)
            tx.redact_ledger("changeset", cs.id, CHANGESET_FIELDS)
        # The request a change answered carries the same one-line summary as its note.
        request = tx.get("request", cs.data.get("request") or "")
        if request is not None and (note := _say(request.data.get("note"), names)) != request.data.get("note"):
            tx.update("request", request.id, {"note": note}, ctx, read_version=request.version)
            tx.redact_ledger("request", request.id, REQUEST_FIELDS)
    forget_reach.reach(tx, store, person_id, plan, ctx, root=root)
    # The ledger keeps the list of what was given up (ids and field names, never values), so the other computer's
    # comparison and an Undo read exactly what this forget redacted.
    tx.note_ledger(
        ctx,
        "person",
        person_id,
        tx.get("person", person_id).version,
        forget_reach.REACH_FIELD,
        forget_reach.reach_list(tx),
    )


def forget_person(ws: Any, store: Store, cfg: Any, person_id: str, *, read_version: int, summary: str) -> str:
    """The person's own forgetting of someone: one change, then the saved texts and stored files nothing holds any
    more are deleted, the private evaluation cases that hold them are removed, and the readable export is written again
    and its history rebuilt. Refused before anything changes when the history can't be rebuilt. Returns the changeset
    id."""
    from engine import forget_reach
    from engine.applier import apply_as_person
    from engine.redactions import rebuild_export, rebuild_problem

    why = rebuild_problem(ws)
    if why is not None:
        raise StoreError(why)
    view = store.read()
    before = forget_reach.held_by(view)
    plan = forget_reach.plan_of(view, person_id, ws.root)
    cs_id = apply_as_person(
        store, cfg, [{"op": "person.forget", "person": person_id, "read_version": read_version}], summary
    )
    forget_reach.drop_gone(ws.root, before, forget_reach.held_by(store.read()))
    forget_reach.forget_evals(ws.root, plan)
    rebuild_export(ws, store)
    return cs_id


def _say(text: Any, ids: Any) -> Any:
    """A text with each of the person's names, addresses and numbers replaced by its marker."""
    if not isinstance(text, str) or not text:
        return text
    return ids.say(text)


def _scrub_changeset(data: dict[str, Any], person_id: str, names: Any) -> dict[str, Any]:
    """The fields of an earlier change to write so it no longer holds the person, or an empty dict when it holds
    nothing of them. An op that is about the person keeps only which record it was about; every op's words (its label
    and the reason it was held) lose the person's names, and so do the change's summary and topic."""
    out: dict[str, Any] = {}
    outcomes = []
    for outcome in data.get("ops", []):
        op = outcome.get("op") or {}
        about = person_id in (
            (op.get("record") or {}).get("id"),
            op.get("id"),
            op.get("person"),
        ) or any(r.get("id") == person_id for r in outcome.get("records") or [])
        new = {**outcome}
        if about:
            new["op"] = {k: v for k, v in op.items() if k in _OP_KEEPS}
        for key in ("label", "reason"):
            if about and key == "label":
                new[key] = None
            elif key in new:
                new[key] = _say(new[key], names)
        outcomes.append(new)
    if outcomes != data.get("ops", []):
        out["ops"] = outcomes
    for field in ("summary", "topic"):
        said = _say(data.get(field), names)
        if said != data.get(field):
            out[field] = said
    return out
