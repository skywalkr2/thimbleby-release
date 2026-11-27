"""Which requests What changed lists as rows, and its menu count: results and what needs the person, never work in
progress and never the assistant's own jobs. One place, so the page and the count agree (design 7.3)."""

from __future__ import annotations

from typing import Any

from engine.titles import title_for

#: Task kinds of a scheduled job whose result is something the person reads, so it stays a row.
_RESULT_TASKS = frozenset({"follow-on", "notes"})


def in_progress(request: dict[str, Any]) -> bool:
    """Work the assistant has not finished: it shows in the status, never as a row. Work held up by a cause the person
    can see and may clear (a paused account, no network, a wait for a level) is a stop, and stays a row."""
    return not request.get("dismissed") and request["state"] in ("queued", "running") and not request.get("cause")


def needs_the_person(request: dict[str, Any]) -> bool:
    return request["state"] in ("needs_you", "failed") and not request.get("dismissed")


def own_job(request: dict[str, Any]) -> bool:
    """A job the assistant started on its own schedule from no input (learning from a correction, reading what a side's
    items are about, a filing pass): nothing the person handed in. One that stopped and needs the person stays."""
    if request.get("source") or request.get("origin") not in ("schedule", "assistant"):
        return False
    if (request.get("task") or "") in _RESULT_TASKS:
        return False
    return not needs_the_person(request)


def without_subject(request: dict[str, Any], changeset: dict[str, Any] | None, cfg: Any) -> bool:
    """A change the person's own screen made whose title has no words of its own (a bare "Your change")."""
    if request.get("source") or request.get("origin") != "pm" or request.get("task") == "action-work":
        return False
    if needs_the_person(request):
        return False
    title = title_for(
        request,
        None,
        changeset,
        people=None,  # type: ignore[arg-type]  # a request with no input never names a person
        skip=[],
        min_words=cfg.language.title_min_words,
    )
    return title.kind == "screen" and not title.topic


def read_nothing(request: dict[str, Any], changeset: dict[str, Any] | None) -> bool:
    """A finished read of an outside input that recorded no op: nothing changed, so it is not a row of What changed
    (results only). Handled for you lists it, as mail read with nothing to do; the page, the count and that list use
    this one rule."""
    d = request
    if d["state"] != "done" or d.get("origin") != "input" or d.get("set_aside") or d.get("auto_closed"):
        return False
    if d.get("folded_into") or not d.get("changeset") or changeset is None:
        return False
    return not changeset["ops"] and changeset["status"] == "applied"


def nothing_to_show(request: dict[str, Any], changeset: dict[str, Any] | None) -> bool:
    """A finished change the person's own screen made that lists no op to read: opening it would say nothing, so it is
    not a row. Everything else keeps its row, a held, undone or stopped change among it."""
    if request.get("source") or request.get("origin") != "pm" or request["state"] != "done" or changeset is None:
        return False
    ops = changeset["ops"]
    return changeset["status"] == "applied" and not any(not bookkeeping_op(o, ops) for o in ops)


def bookkeeping_op(o: dict[str, Any], ops: list[dict[str, Any]]) -> bool:
    """Whether an op of a change is no news to the person: their own organization set to the one the same change just
    made (they work for the business they added), which a record's Activity leaves out as well."""
    op = o["op"]
    if (
        o.get("status") != "applied"
        or op.get("op") != "record.set"
        or op.get("kind") != "person"
        or op.get("field") != "org"
    ):
        return False
    return any(
        other.get("status") == "applied"
        and other["op"].get("op") == "project.add"
        and op.get("value") in (other["op"].get("organization"), other["op"].get("name"))
        for other in ops
    )


def hidden(request: dict[str, Any], changeset: dict[str, Any] | None, cfg: Any) -> bool:
    """Whether What changed leaves the request out (and its menu count with it)."""
    return (
        in_progress(request)
        or own_job(request)
        or without_subject(request, changeset, cfg)
        or nothing_to_show(request, changeset)
    )
