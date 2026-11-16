"""What the person's corrections teach the assistant's mail sorting (design 6.5 and 6.22).

Two corrections each propose one lesson for the sorting task kind, in the sender's own words: bringing in a message the
assistant's sorting (or a built-in rule) set aside, and setting aside by hand a message the sorting kept. The app writes
the lesson itself from the message's sender, so no run reads the message again and no subject or text of the message
reaches a lesson. It is a proposal: it guides the sorting only once the person keeps it, and it merges with a lesson
that already says the same or waits out one the person discarded.
"""

from __future__ import annotations

from typing import Any

from engine import knowledge, set_aside
from engine.mail_sorting import KIND, RULE
from engine.names import People
from engine.ops import LessonAddOp
from engine.records import Scope
from engine.storage import WriteContext

#: The rule names the core's built-in set-aside rules gave mail before the assistant's sorting placed it.
BUILT_IN_RULES = ("Automated notices", "Bulk mail", "Promotions and social")
_WRITE = WriteContext(actor="pm", trust="trusted", op="sorting.lesson")


def set_aside_by_sorting(mark: dict[str, Any] | None) -> bool:
    """Whether a set-aside mark came from the assistant's sorting or a built-in rule, not from the person or their own
    rule: only those are corrections of the sorting."""
    return bool(mark) and (mark.get("by") == "assistant" or mark.get("rule") in (RULE, *BUILT_IN_RULES))


def _who(cfg: Any, address: str) -> str:
    """The sender as a lesson names it: their domain when anyone may have a rule for it, else the address."""
    return set_aside.offerable_domain(address, cfg) or address


def lesson_text(who: str, teaches: str) -> str:
    """The lesson's words. `teaches` is "work" (it was brought in) or a section the person set it aside as."""
    if teaches == "work":
        return f"Mail from {who} matters to you: read what it says before setting it aside as sales or a notice."
    word = "sales mail" if teaches == "sales" else "an automatic notice"
    return f"Mail from {who} doesn't need you: set it aside as {word}."


def propose(ws: Any, store: Any, cfg: Any, snapshot_id: str, teaches: str) -> str | None:
    """Propose the sorting lesson one correction of this message teaches, as the app's own proposal. Returns the id of
    the lesson (a new one, or the one it merged into), or None when learning is off or the sender isn't known."""
    knowledge_cfg = cfg.dispatch.knowledge
    snap = store.read().get("snapshot", snapshot_id)
    if not knowledge_cfg.learn or snap is None:
        return None
    address = set_aside.address_of(snap, ws)
    if not address:
        return None
    standing = knowledge.Standing(
        person=False,
        pm=People(store, cfg).pm,
        origin="assistant",
        trust="untrusted",  # the sender comes from outside; the person's Keep makes the wording their own
        source=None,
        request=None,
        now=store.clock(),
        hold_days=knowledge_cfg.discards_hold_days,
        alike=knowledge_cfg.discard_similarity,
    )
    op = LessonAddOp(text=lesson_text(_who(cfg, address), teaches), applies_to=Scope(task_kinds=[KIND]))
    with store.transaction() as tx:
        return knowledge.apply(tx, op, _WRITE, standing)[0]["id"]
