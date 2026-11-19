"""What the assistant has cost so far, from the recorded runs: today's and this month's total (UTC) and whether either
is near its limit. The totals are the spending boundary's own (`engine/ai/spending.py`): the recorded runs plus what
the calls still running hold, so a status view shows what the limits count."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from engine.ai import spending
from engine.config import Config
from engine.storage import Store


@dataclass(frozen=True)
class Spend:
    today_usd: float
    month_usd: float
    per_day_usd: float
    per_month_usd: float
    warn_today: bool
    warn_month: bool
    #: Of the totals, the estimates of calls that got no answer and may have been charged.
    maybe_today_usd: float = 0.0
    maybe_month_usd: float = 0.0

    @property
    def warn(self) -> bool:
        return self.warn_today or self.warn_month


def spend(store: Store, cfg: Config, now: datetime | None = None) -> Spend:
    now = now or datetime.now(UTC)
    day, month = spending.totals(store, now)
    maybe_day, maybe_month = spending.may_have_been_charged(store, now)
    budgets = cfg.ai.budgets
    return Spend(
        today_usd=day,
        month_usd=month,
        per_day_usd=budgets.per_day_usd,
        per_month_usd=budgets.per_month_usd,
        warn_today=day > 0 and day >= budgets.warn_at * budgets.per_day_usd,
        warn_month=month > 0 and month >= budgets.warn_at * budgets.per_month_usd,
        maybe_today_usd=maybe_day,
        maybe_month_usd=maybe_month,
    )
