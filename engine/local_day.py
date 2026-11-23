"""The person's own day for a stored or written time.

A time is written with an offset (often UTC), so its first ten characters are the day where the writer was, never
necessarily where the person is. A date-only value is never derived from a time by cutting its text: the time is turned
into the person's zone first, then its date is taken. This is the one place that does it.

Plain functions: they take a text or a time and a zone, and read no records or clock.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone_of(cfg: Any) -> tzinfo:
    """The person's time zone from the settings; UTC when none is set or the settings are not at hand."""
    try:
        return ZoneInfo(cfg.workspace.user.timezone)
    except (AttributeError, ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def day_of(stamp: Any, here: tzinfo) -> date:
    """The day a stored date or time falls on where the person is. A date, or text that is only a date, is that day. A
    time with an offset is turned into `here` first; one with none was written where the person is and keeps its day.
    Raises ValueError for text that is neither."""
    if isinstance(stamp, datetime):
        moment = stamp
    elif isinstance(stamp, date):
        return stamp
    else:
        text = str(stamp).strip()
        if len(text) == 10:
            return date.fromisoformat(text)
        moment = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    return (moment.astimezone(here) if moment.tzinfo is not None else moment).date()


def day_text(stamp: Any, here: tzinfo) -> str:
    """`day_of` as an ISO date text."""
    return day_of(stamp, here).isoformat()


def maybe_day(stamp: Any, here: tzinfo) -> date | None:
    """`day_of`, or none when the value names no day."""
    try:
        return day_of(stamp, here)
    except (TypeError, ValueError):
        return None
