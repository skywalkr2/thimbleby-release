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


def hidden(request: dict[str, Any], changeset: dict[str, Any] | None, cfg: Any) -> bool:
    """Whether What changed leaves the request out (and its menu count with it)."""
    return in_progress(request) or own_job(request) or without_subject(request, changeset, cfg)
