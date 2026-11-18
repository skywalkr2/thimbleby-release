"""A pause the person states, held as a standing rule (design 6.22, 6.19).

A rule can name a record it pauses (`pauses`) and the words for when it ends (`until`). While the rule is active, a run
on an input that is a change to that record may record facts and nothing that questions the person's unfinished work:
no question to anyone. The rule is read by every run like any standing rule; this module is what holds the line when
the assistant asks anyway. The person saying it is ready retires the rule, and the review of the latest version then
runs. Plain rules over records: nothing here reads the model's claim of what it followed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.storage import WriteContext

_ENGINE = WriteContext(actor="engine", trust="trusted", op="rule.paused_review")

#: The ops a paused document yields none of: they put the person's unfinished text in question.
PAUSED_OPS = frozenset({"question.add"})


def paused_ids(view: Any) -> dict[str, Any]:
    """The active pause rules by the id of the record each one pauses."""
    return {r.data["pauses"]: r for r in view.list("rule") if r.data.get("status") == "active" and r.data.get("pauses")}


def identities(view: Any, source_id: str | None, request_id: str | None) -> set[str]:
    """The ids an input answers to as a document: its source, every earlier version of the same watched item, and the
    record its request is about."""
    found: set[str] = set()
    source = view.get("source", source_id) if source_id else None
    request = view.get("request", request_id) if request_id else None
    if source is not None:
        found.add(source.id)
        watched = source.data.get("watched") or {}
        if watched.get("key"):
            same = (watched.get("source"), watched["key"])
            found |= {
                s.id
                for s in view.list("source")
                if ((s.data.get("watched") or {}).get("source"), (s.data.get("watched") or {}).get("key")) == same
            }
    about = (request.data.get("about") or {}) if request is not None else {}
    if about.get("id"):
        found.add(about["id"])
    return found


def holding(view: Any, source_id: str | None, request_id: str | None) -> list[Any]:
    """The active pause rules that cover this input."""
    paused = paused_ids(view)
    if not paused:
        return []
    ids = identities(view, source_id, request_id)
    return [rule for target, rule in paused.items() if target in ids]


def refusal(rule: Any, op_name: str) -> str:
    """Why an op is refused while the document is paused, for the assistant: what the person said and what to do."""
    return (
        f"{op_name} is held while {rule.id} stands: {rule.data['text']} Until {rule.data['until']}, record what "
        "changed as a fact and ask nothing about it."
    )


def queue_review(tx: Any, rule: Any, now: datetime | None = None) -> str | None:
    """When a pause ends, queue the review it held back: a run on the latest version of the document. Returns the new
    request's id, or None when the pause named no input that exists (nothing to review)."""
    target = rule.data.get("pauses")
    if not target:
        return None
    sources = [s for s in tx.list("source") if s.id == target or target in identities(tx, s.id, None)]
    if not sources:
        return None
    latest = max(sources, key=lambda s: (str(s.data.get("received_at")), s.id))
    moment = (now or datetime.now(UTC)).isoformat()
    return tx.create(
        "request",
        {
            "task": "notes",
            "source": latest.id,
            "origin": "input",
            "state": "queued",
            "waiting": "With the assistant, starting now",
            "created_at": moment,
        },
        _ENGINE,
    ).id
