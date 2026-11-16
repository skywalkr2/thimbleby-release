"""The person's routines: slots they keep for the same thing week after week (design 6.22, "Learning the person from
their mail and calendar"). A routine is a glossary entry that carries a `routine` (weekdays and times). It is proposed
by the weekly look at the person and counts only once the person has kept it; a proposed, discarded or retired one is
never read here.

What the steward does with a kept routine: it is not offered as a free slot (`busy`, read by the time proposals and the
day's capacity), and no reminder lands in it (`clear_of`, read where a reminder is placed and where it reaches the
person). Everything here reads; nothing writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from engine.free_slots import Busy
from engine.records import ROUTINE_DAYS


@dataclass(frozen=True)
class Slot:
    """One kept routine: the entry's id, what it is for, the weekdays (Monday is 0) and the local times it holds."""

    entry: str
    label: str
    days: tuple[int, ...]
    start: time
    end: time


def kept(view: Any) -> list[Slot]:
    """The routines the person kept, in the order they were made."""
    found = []
    for entry in view.list("glossary_entry"):
        d = entry.data
        routine = d.get("routine")
        if d.get("status") != "active" or not routine:
            continue
        found.append(
            Slot(
                entry.id,
                str(d.get("term") or ""),
                tuple(sorted(ROUTINE_DAYS.index(day) for day in routine["days"])),
                time.fromisoformat(routine["start"]),
                time.fromisoformat(routine["end"]),
            )
        )
    return found


def _span(slot: Slot, day: date, tz: tzinfo) -> tuple[datetime, datetime] | None:
    """The moments a routine holds on a day, or None when it doesn't happen that day or a clock change leaves it no
    time."""
    if day.weekday() not in slot.days:
        return None
    begin, finish = datetime.combine(day, slot.start, tz), datetime.combine(day, slot.end, tz)
    return (begin, finish) if finish > begin else None


def busy(slots: list[Slot], tz: tzinfo, first: datetime, last: datetime) -> list[Busy]:
    """What the routines block between two moments: one busy interval for each day each one happens."""
    found: list[Busy] = []
    day = first.astimezone(tz).date() - timedelta(days=1)
    end_day = last.astimezone(tz).date() + timedelta(days=1)
    while day <= end_day:
        for slot in slots:
            span = _span(slot, day, tz)
            if span is not None:
                found.append(Busy(span[0], span[1]))
        day += timedelta(days=1)
    return found


def covering(slots: list[Slot], moment: datetime, tz: tzinfo) -> Slot | None:
    """The routine that holds a moment (its start included, its end not), if any."""
    local = moment.astimezone(tz)
    for slot in slots:
        span = _span(slot, local.date(), tz)
        if span is not None and span[0] <= local < span[1]:
            return slot
    return None


def clear_of(slots: list[Slot], moment: datetime, tz: tzinfo) -> datetime:
    """The first moment at or after `moment` that no routine holds: `moment` itself when none does, else where the
    routine ends (and where the next, back to back, ends)."""
    local = moment.astimezone(tz)
    for _ in range(len(slots) + 1):
        slot = covering(slots, local, tz)
        if slot is None:
            break
        local = datetime.combine(local.date(), slot.end, tz)
    return local if local != moment.astimezone(tz) else moment
