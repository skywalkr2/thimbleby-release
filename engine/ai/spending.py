"""The one boundary every paid AI call passes (design 6.16, "Spending limits"): admitted against the daily, monthly
and per-kind limits before it starts, and recorded as a run with its cost when it ends.

The limits are ceilings. A call is admitted only when what was already spent, plus what the calls still running were
admitted with, plus its own estimate, stays within each limit; the estimate is then held until the call ends, when
its run is recorded and the amount is given back in one step, so the totals never miss it and never count it twice.
A call with no known price holds nothing, and starts only while each limit still has room.

What is held lives in this process only: one ledger and one lock for every thread and every router, by workspace. A
total is the recorded runs' costs (a real cost, an estimated one, or the estimate of a call that may have been
charged) plus what is held.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from engine.money import usd

#: How a run's cost is known, when it is not the service's own figure or worked out from the tokens it reported.
#: `ESTIMATED`: the call was answered and gave no figure, so the cost is the estimate. `MAYBE_CHARGED`: the call may
#: have reached the service and no answer came back, so its estimate is counted until the service's own figures say.
ESTIMATED, MAYBE_CHARGED = "estimated", "maybe_charged"
#: The failures of a call that may have reached the service: it timed out, or the connection was lost after it was
#: made. A call that could not connect at all, or that the service refused, sent nothing that is charged.
MAY_HAVE_REACHED = frozenset({"timeout", "provider_down"})
#: The kind of work an account check's own model calls are recorded as.
ACCOUNT_CHECK = "account_check"


class BudgetReached(Exception):
    """A spending limit stops new runs. The message says which and until when; `period` is "day" or "month" when
    one of the limits here refused it."""

    def __init__(self, message: str, period: str | None = None):
        super().__init__(message)
        self.period = period


@dataclass
class Hold:
    """What one running call was admitted with."""

    key: str
    token: int
    kind: str | None
    usd: float
    at: datetime


_LOCK = threading.RLock()
_HELD: dict[str, dict[int, Hold]] = {}
_TOKENS = itertools.count(1)


def _key(store: Any) -> str:
    return str(store.path)


def held(store: Any) -> list[Hold]:
    """What the calls still running on this workspace were admitted with."""
    with _LOCK:
        return list(_HELD.get(_key(store), {}).values())


def _same_month(at: datetime, now: datetime) -> bool:
    return (at.year, at.month) == (now.year, now.month)


def recorded(store: Any, now: datetime, kind: str | None = None) -> tuple[float, float]:
    """USD the recorded runs cost today and this month (UTC), for one kind of work when `kind` is given."""
    day = month = 0.0
    for run in store.read().list("run"):
        if kind is not None and run.data.get("task") != kind:
            continue
        cost = run.data.get("cost_usd") or 0.0
        at = datetime.fromisoformat(run.data["started_at"])
        if _same_month(at, now):
            month += cost
            if at.date() == now.date():
                day += cost
    return day, month


def may_have_been_charged(store: Any, now: datetime) -> tuple[float, float]:
    """Of the recorded costs, how much today and this month (UTC) is the estimate of a call that got no answer."""
    day = month = 0.0
    for run in store.read().list("run"):
        if run.data.get("cost_basis") != MAYBE_CHARGED:
            continue
        cost = run.data.get("cost_usd") or 0.0
        at = datetime.fromisoformat(run.data["started_at"])
        if _same_month(at, now):
            month += cost
            if at.date() == now.date():
                day += cost
    return day, month


def totals(store: Any, now: datetime, kind: str | None = None) -> tuple[float, float]:
    """USD spent today and this month (UTC): the recorded runs plus what the running calls hold."""
    with _LOCK:
        day, month = recorded(store, now, kind)
        for hold in _HELD.get(_key(store), {}).values():
            if (kind is None or hold.kind == kind) and _same_month(hold.at, now):
                month += hold.usd
                if hold.at.date() == now.date():
                    day += hold.usd
    return day, month


def _over(total: float, amount: float, limit: float) -> bool:
    """Whether a call estimated at `amount` can't start with `total` already counted: the limit is used up, or the
    call would take the total past it."""
    return total >= limit or total + amount > limit + 1e-9


def _refuse(budgets: Any, kind: str | None, amount: float, day: float, month: float, by_kind: bool) -> None:
    limits = budgets.per_task.get(kind) if by_kind else budgets
    scope = " for this kind of work" if by_kind else ""
    name = "budget for this kind of work" if by_kind else "AI budget"
    for total, limit, when, wait, period in (
        (month, limits.per_month_usd, "this month's", "Paused", "month"),
        (day, limits.per_day_usd, "today's", "Paused until tomorrow", "day"),
    ):
        if limit is None or not _over(total, amount, limit):
            continue
        if total >= limit:
            raise BudgetReached(f"{wait}: {when} {name} ({usd(limit)}) is used up.", period)
        raise BudgetReached(
            f"{wait}: this run is estimated at {usd(amount)}, more than what is left of {when} budget{scope} "
            f"({usd(max(0.0, limit - total))} of {usd(limit)}).",
            period,
        )


def check(store: Any, budgets: Any, kind: str | None, now: datetime, amount: float = 0.0) -> None:
    """Raise `BudgetReached` when a call of `kind` estimated at `amount` can't start now. Nothing is held."""
    with _LOCK:
        if kind and budgets.per_task.get(kind) is not None:
            _refuse(budgets, kind, amount, *totals(store, now, kind), by_kind=True)
        _refuse(budgets, kind, amount, *totals(store, now), by_kind=False)


def admit(store: Any, budgets: Any, kind: str | None, amount: float | None, now: datetime) -> Hold:
    """Admit one call and hold its estimate (`amount`; None when its price isn't known, which holds nothing). Raises
    `BudgetReached` when it doesn't fit. Every admitted call ends in `release`, or `settle` with its run."""
    amount = max(0.0, amount or 0.0)
    with _LOCK:
        check(store, budgets, kind, now, amount)
        hold = Hold(_key(store), next(_TOKENS), kind, amount, now)
        _HELD.setdefault(hold.key, {})[hold.token] = hold
    return hold


def settling() -> Any:
    """The boundary's lock, for a caller that records several runs and gives back one hold in one step."""
    return _LOCK


def release(hold: Hold | None) -> None:
    """Give back what a call held. Giving back twice changes nothing."""
    if hold is None:
        return
    with _LOCK:
        calls = _HELD.get(hold.key)
        if calls is not None:
            calls.pop(hold.token, None)
            if not calls:
                _HELD.pop(hold.key, None)


def reduce(hold: Hold | None, part: float) -> None:
    """Give back part of a hold that covers several calls, for one of them that ended with nothing to record."""
    if hold is not None:
        with _LOCK:
            hold.usd = max(0.0, hold.usd - part)


def settle(store: Any, hold: Hold | None, data: dict[str, Any], context: Any, *, part: float | None = None) -> str:
    """Record a call's run and give back what it held, in one step, so no total sees both or neither. With `part`,
    only that much of the hold is given back and the rest stays held (a hold that covers several calls). Returns the
    run's id."""
    with _LOCK:
        with store.transaction() as tx:
            run_id = tx.create("run", data, context).id
        if hold is not None and part is not None:
            hold.usd = max(0.0, hold.usd - part)
        else:
            release(hold)
    return run_id
