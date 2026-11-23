"""Which facts a draft for someone else may state (design 6.19, 6.22).

A draft names the facts its content states. A fact the assistant only inferred is never stated to anyone else, and a
fact older than its freshness limit (by kind, `steward.facts.freshness_days`) is held for the person to check. A fact
the person confirmed rests on them and passes. Plain rules over explicit inputs: nothing is written and no AI runs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from engine.local_day import day_of, zone_of

#: A fact's own words count as stated in a draft only when they run at least this long; a shorter one is too common.
MIN_WORDS = 4


@dataclass(frozen=True)
class Stale:
    fact: Any
    as_of: date
    days: int
    limit: int


def inferred(view: Any, fact_ids: list[str], parts: Iterable[str] = ()) -> list[Any]:
    """The facts among those a draft names, or whose words the draft's text states, that rest only on the assistant's
    inference. A fact the person confirmed (its basis is theirs) is not one."""
    found = []
    text = " ".join(" ".join(p.lower().split()) for p in parts)
    for stored in view.list("fact"):
        if stored.data.get("basis") != "inferred":
            continue
        words = " ".join(str(stored.data.get("text") or "").lower().split())
        if stored.id in fact_ids or (len(words.split()) >= MIN_WORDS and words in text):
            found.append(stored)
    return found


def limit_days(cfg: Any, fact: dict[str, Any]) -> int:
    """The days a fact of this kind may be old: the limit for its kind of day, else the one for any other fact."""
    limits = cfg.steward.facts.freshness_days
    return int(getattr(limits, fact.get("on_kind") or "other", limits.other))


def stale(view: Any, cfg: Any, fact_ids: list[str], today: date) -> list[Stale]:
    """The named facts older than their limit, measured from the day each was true as of. A fact with no such day, and a
    limit of zero, are never stale."""
    found = []
    for fact_id in fact_ids:
        stored = view.get("fact", fact_id)
        if stored is None or not stored.data.get("as_of"):
            continue
        as_of = stored.data["as_of"]
        as_of = as_of if isinstance(as_of, date) else day_of(as_of, zone_of(cfg))
        limit = limit_days(cfg, stored.data)
        days = (today - as_of).days
        if limit and days > limit:
            found.append(Stale(stored, as_of, days, limit))
    return found
