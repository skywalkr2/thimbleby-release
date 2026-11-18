"""The alpha's measures for one person (design 6.32, "The alpha's numbers"): five numbers over the first week of the
workspace, read from the records alone, on the person's own clock. Nothing here calls AI, sends anything or keeps a
second copy: the numbers are worked out each time they are asked for, and they hold no name, title or record text.

- Days used: the days of the first week on which the person did anything of their own (a ledger entry written by the
  person, or a visit to a screen that looks over the assistant's work).
- Cost per day: what the AI runs of the first week cost in all, over the days so far. A run with no known price counts
  as nothing; a workspace that has used no AI costs 0.
- Corrections per day: the person's corrections of the assistant's work (`quality.CORRECTIONS`) in the first week, over
  the days so far.
- Drafts sent as written and edited: the acts the assistant drafted that the person said yes to in the first week,
  split by whether the person changed the act (`act.edit`) before their last yes.
- Time from install to a first result: from the workspace's first record to the first AI result the person could see
  (a request the assistant finished that went to review or was done).

The first week starts on the day of the workspace's first record. Until a week has passed the figures cover the days so
far, and the result says so (`complete` is false).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from engine import gate_measures, quality

#: The length of the first week, in days.
WEEK_DAYS = 7
#: The person's own writes in the ledger.
_PERSON = "pm"
#: The states of a request in which its result can be seen.
_SEEN = ("review", "done")


@dataclass(frozen=True)
class AlphaMeasures:
    first_start: datetime | None  # None when the workspace holds nothing yet
    since: date | None
    until: date | None  # the last day counted: today, or the seventh day
    days_so_far: int  # the days counted, 0 with nothing yet, at most WEEK_DAYS
    complete: bool  # a whole week has passed
    days_used: int
    cost_total: float
    cost_per_day: float
    corrections: int
    corrections_per_day: float
    sent_as_written: int
    sent_edited: int
    first_result_minutes: int | None  # None until a first result has been seen


def _op_of(entry: dict[str, Any]) -> str:
    return str(entry["op"]).split("#")[0]


def _per_day(total: float, days: int) -> float:
    return total / days if days else 0.0


def sent_split(view: Any, ledger: list[dict[str, Any]], win: gate_measures.Window) -> tuple[int, int]:
    """(as written, edited): the acts the assistant drafted that the person said yes to in the window."""
    mine = {a.id for a in view.list("act") if a.data.get("made_by") == "assistant"}
    edits: dict[str, list[int]] = {}
    yes: dict[str, dict[str, Any]] = {}
    for entry in ledger:
        if entry["kind"] != "act" or entry["record_id"] not in mine:
            continue
        if _op_of(entry) == "act.edit":
            edits.setdefault(entry["record_id"], []).append(entry["seq"])
        elif _op_of(entry) == "act.approve" and entry["field"] == "status" and entry["after"] == "approved":
            yes[entry["record_id"]] = entry  # the last yes wins: ledger entries come oldest first
    written = edited = 0
    for act_id, entry in yes.items():
        when = gate_measures._moment(entry["at"])
        if when is None or not win.start <= when <= win.end:
            continue
        if any(seq < entry["seq"] for seq in edits.get(act_id, ())):
            edited += 1
        else:
            written += 1
    return written, edited


def first_result(view: Any, ledger: list[dict[str, Any]]) -> datetime | None:
    """When the first AI result the person could see was ready: the first request with an answered run that went to
    review or was done."""
    answered = {r.data.get("request") for r in view.list("run") if r.data.get("outcome") == "ok"}
    found = [
        gate_measures._moment(e["at"])
        for e in ledger
        if e["kind"] == "request" and e["field"] == "state" and e["after"] in _SEEN and e["record_id"] in answered
    ]
    moments = [m for m in found if m is not None]
    return min(moments) if moments else None


def alpha_measures(view: Any, now: datetime, here: tzinfo) -> AlphaMeasures:
    ledger = view.ledger()
    stamps = [m for m in (gate_measures._moment(e["at"]) for e in ledger) if m is not None]
    if not stamps:
        return AlphaMeasures(None, None, None, 0, False, 0, 0.0, 0.0, 0, 0.0, 0, 0, None)
    first = min(stamps)
    since = first.astimezone(here).date()
    today = now.astimezone(here).date()
    until = min(today, since + timedelta(days=WEEK_DAYS - 1))
    days = max(0, (until - since).days + 1)
    start = datetime.combine(since, time(0), tzinfo=here).astimezone(UTC)
    end = min(now, gate_measures.end_of(until, here))
    win = gate_measures.Window(since, until, start, end)

    used = {
        d
        for d in (gate_measures._day_of(e["at"], here) for e in ledger if e["actor"] == _PERSON)
        if d is not None and since <= d <= until
    }
    used |= {d.day for d in gate_measures.review_measure(view, win, here).days}

    cost = 0.0
    for run in view.list("run"):
        when = gate_measures._moment(run.data.get("started_at"))
        if when is not None and win.start <= when <= win.end:
            cost += run.data.get("cost_usd") or 0.0

    corrections = 0
    for signal in view.list("signal"):
        when = gate_measures._moment(signal.data["at"])
        if signal.data["kind"] in quality.CORRECTIONS and when is not None and win.start <= when <= win.end:
            corrections += 1

    written, edited = sent_split(view, ledger, win)
    result = first_result(view, ledger)
    return AlphaMeasures(
        first_start=first,
        since=since,
        until=until,
        days_so_far=days,
        complete=days >= WEEK_DAYS,
        days_used=len(used),
        cost_total=round(cost, 6),
        cost_per_day=_per_day(cost, days),
        corrections=corrections,
        corrections_per_day=_per_day(corrections, days),
        sent_as_written=written,
        sent_edited=edited,
        first_result_minutes=None if result is None else max(0, int((result - first).total_seconds() // 60)),
    )
