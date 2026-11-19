"""Facts that replace one another (design 6.22).

A fact says which fact it replaces (`supersedes`). The older fact is never edited: what replaced it is worked out from
the newer fact, so undoing the newer fact brings the older one back with no second write to undo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import Any

from engine.storage import StoreError


def superseded_by(view: Any, fact_id: str) -> str | None:
    """The id of the fact that replaces this one, or None when it is still the latest word."""
    for stored in view.list("fact"):
        if stored.data.get("supersedes") == fact_id:
            return stored.id
    return None


def replaced_ids(facts: Iterable[Any], hide: Callable[[Mapping[str, Any]], bool] | None = None) -> set[str]:
    """The ids of the facts a reader finds replaced: each fact a stored fact replaces, counting only replacements the
    reader may see. A newer fact `hide` keeps from the reader replaces nothing for them, so the older fact stays where
    they look."""
    return {f.data["supersedes"] for f in facts if f.data.get("supersedes") and not (hide is not None and hide(f.data))}


def outside_replaces_trusted(view: Any, fact_id: str | None, own_words: bool) -> bool:
    """Whether a replacement must wait for the person: it does not come from the person's own words, and the fact it
    names is one they trust. Until they say yes both stand: the trusted fact stays where readers look, and the new
    one is only a claim on the line that asks them. A replacement of a fact that itself came from outside needs no
    one's yes."""
    if fact_id is None or own_words:
        return False
    older = view.get("fact", fact_id)
    return older is not None and older.data.get("trust", "trusted") == "trusted"


def check_replaces(tx: Any, fact_id: str | None) -> None:
    """Refuse a replacement that points at nothing, or at a fact something else already replaced."""
    if fact_id is None:
        return
    if tx.get("fact", fact_id) is None:
        raise StoreError(f"there is no fact {fact_id} to replace")
    newer = superseded_by(tx, fact_id)
    if newer is not None:
        raise StoreError(f"{fact_id} was already replaced by {newer}; replace that one instead")


def received_on(tx: Any, request_id: str | None, source_id: str | None, here: Any) -> date | None:
    """The day an input was received: its source's received time, else when the request was made; None when neither
    is known."""
    from engine.today import local_day

    source = tx.get("source", source_id) if source_id else None
    request = tx.get("request", request_id) if request_id else None
    for stored, field in ((source, "received_at"), (request, "created_at")):
        value = stored.data.get(field) if stored is not None else None
        if value:
            return local_day(datetime.fromisoformat(str(value)), here)
    return None
