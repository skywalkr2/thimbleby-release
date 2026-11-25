"""Where an answered question stands until the run on the answer has judged it.

An answer is stored when the person gives it, and the run on it decides whether it settles the question. Until that run
has finished the question isn't settled: it is being read, or, when the run can't go (no account to run on, over a limit
or budget, an error), its answer is waiting to be read. Once the run has judged the answer the question leaves its lists
(or comes back open and reworded when the answer was unclear). Every list that shows a question asks this one function.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from engine.answer_effect import judged_question

#: Causes that keep a queued request from starting until something changes, with or without a time.
_STOPS = ("identity", "no_account", "data_level", "no_person", "no_fit")
_TIMED = ("paused", "retry", "offline")


@dataclass(frozen=True)
class AnswerState:
    """`reading`: the run is queued or running. `waiting`: it can't go, or stopped; `why` says why and until when in
    the request's own words."""

    state: Literal["reading", "waiting"]
    request: str
    why: str | None = None


def _waits(data: dict[str, Any], now: datetime) -> bool:
    cause = data.get("cause") or {}
    kind = cause.get("kind")
    if kind in _STOPS:
        return True
    if kind in _TIMED and cause.get("until"):
        until = datetime.fromisoformat(str(cause["until"]))
        return (until if until.tzinfo else until.replace(tzinfo=UTC)) > now
    return False


def answer_states(reader: Any, now: datetime | None = None) -> dict[str, AnswerState]:
    """The answered questions whose answer has not been judged yet, by question id. A question not in the result is
    settled, or was never answered in words. The newest run on the answer counts."""
    now = now or datetime.now(UTC)
    found: dict[str, AnswerState] = {}
    for request in reader.requests_unfinished():
        data = request.data
        question = judged_question(reader, data)
        if question is None or question.data.get("status") != "answered":
            continue
        source = reader.get("source", data["source"])
        if source is None or source.data.get("kind") not in ("note:answered", "note:answered_for"):
            continue
        state = data["state"]
        if state in ("review", "done"):
            continue  # the run finished and judged it
        waiting = state in ("needs_you", "failed") or (state == "queued" and _waits(data, now))
        found[question.id] = AnswerState(
            "waiting" if waiting else "reading", request.id, data.get("waiting") if waiting else None
        )
    return found
