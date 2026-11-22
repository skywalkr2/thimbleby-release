"""Whether the assistant is still learning from older mail: the notice above Today's lines while a read of older mail is
under way (design 6.32). It is a notice, never a line, because Today's lines are things the person does."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Request states of older-mail work that has finished and counts toward how far along the reading is.
_FINISHED = ("done", "review")
#: Request states of older-mail work that is under way.
_UNDER_WAY = ("queued", "running")


@dataclass(frozen=True)
class Learning:
    active: bool
    #: Batches of older mail read, and all the batches of the reach so far (0 when not known).
    read: int = 0
    of: int = 0


def standing(view: Any) -> Learning:
    """The state of the older-mail reading: active while any of its requests is queued or running, with the batches
    finished of the batches handed in. A request waiting for the person's go, stopped or dismissed is not under way."""
    under = finished = 0
    for r in view.list("request"):
        d = r.data
        if not d.get("intake_older") or d.get("dismissed"):
            continue
        if d.get("state") in _UNDER_WAY:
            under += 1
        elif d.get("state") in _FINISHED:
            finished += 1
    if not under:
        return Learning(False)
    return Learning(True, read=finished, of=finished + under)
