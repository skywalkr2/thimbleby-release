"""A watched source to follow or only to understand (design 6.22).

A source the person follows holds work that is theirs to track. A source they only understand (another group's page or
feed) is read, summarized and kept as facts: the assistant adds no to-do, question or follow-up message from it, and the
check `understand-tracks` returns a run that does once, then holds it for the person.
"""

from __future__ import annotations

from typing import Any

from engine.ops import ActDraftOp, ActionAddOp, OpModel, QuestionAddOp

FOLLOW = "follow"
UNDERSTAND = "understand"
#: What a source of each kind is when it is added: mail, a calendar, a capture mailbox and a folder are the person's
#: to follow; anything else (a page, a feed, a tracker) starts as another group's, to understand.
FOLLOWED_KINDS = ("mail", "calendar")


def stance_of(cfg: Any, source_id: str | None) -> str:
    """The stance of a configured source; a source that isn't listed (a note, a hand-in) is followed."""
    found = next((s for s in cfg.watch.sources if s.id == source_id), None) if source_id else None
    return found.stance if found is not None else FOLLOW


def default_stance(connector: str, reads: list[str], capture: bool = False) -> str:
    """The stance a new source of this kind starts with."""
    if reads and any(r in FOLLOWED_KINDS for r in reads):
        return FOLLOW
    if capture or connector in ("folder", "capture"):
        return FOLLOW
    return UNDERSTAND


def watched_source(view: Any, saved_source: str | None) -> str | None:
    """The watched source an input came from, by its id, when the saved input was handed in by one."""
    record = view.get("source", saved_source) if saved_source else None
    watched = record.data.get("watched") if record is not None else None
    return watched.get("source") if watched else None


def finding(op: OpModel, view: Any, cfg: Any, saved_source: str | None) -> str | None:
    """The message of `understand-tracks` for an op from a source the person only understands that would have the
    person track something: a to-do, a question or a follow-up message. Facts and notes are what such a source
    gives."""
    tracks = op.target.kind == "message" if isinstance(op, ActDraftOp) else isinstance(op, (ActionAddOp, QuestionAddOp))
    if not tracks:
        return None
    source = watched_source(view, saved_source)
    if source is None or stance_of(cfg, source) != UNDERSTAND:
        return None
    return (
        "this source is another group's, kept only to understand: record what it says as facts and add no to-do, "
        "question or follow-up from it"
    )
