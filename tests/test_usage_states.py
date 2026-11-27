from datetime import UTC, datetime

from engine.usage import budget_state


def test_budget_state_distinguishes_four_states():
    assert budget_state(0, 10, 0.8) == "normal"
    assert budget_state(8, 10, 0.8) == "approaching"
    assert budget_state(10, 10, 0.8) == "reached"
    assert budget_state(10.5, 10, 0.8) == "exceeded"


def test_spend_reset_times_roll_over_the_day_and_the_year():
    from types import SimpleNamespace

    from engine import usage

    budgets = SimpleNamespace(per_day_usd=1.0, per_month_usd=10.0, warn_at=0.8)
    cfg = SimpleNamespace(ai=SimpleNamespace(budgets=budgets))
    orig = usage.spending
    usage.spending = SimpleNamespace(totals=lambda s, n: (0.0, 0.0), may_have_been_charged=lambda s, n: (0.0, 0.0))
    try:
        s = usage.spend(None, cfg, datetime(2026, 12, 31, 15, 0, tzinfo=UTC))
    finally:
        usage.spending = orig
    assert s.day_resets_at.startswith("2027-01-01T00:00:00")
    assert s.month_resets_at.startswith("2027-01-01T00:00:00")
