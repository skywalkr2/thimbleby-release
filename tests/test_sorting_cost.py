"""What a typical day of the assistant's sorting costs (S-0544): the day's count from the mail read, the packet's
measured size, the price of the account that would sort, a plan's runs, and no account at all."""

import statistics
from datetime import UTC, datetime, time, timedelta

import pytest

from engine import sorting_cost
from engine.ai.calibration import estimate_tokens
from engine.ai.router import Router
from engine.config.schema import Price
from engine.mail_sorting import OUTPUT_TOKENS_PER_MESSAGE, build_task
from tests.test_mail_sorting import make, read, unplaced
from tests.test_set_aside import NOW

PER_DAY = (4, 6, 9)  # the fixture days: messages read on each of three days


def _hours_back(day: int, n: int) -> float:
    """How long before NOW a fixture message of `day` (1 = yesterday, and so on) was received: in the morning of that
    UTC day, so a day's messages never straddle midnight whatever the hour the test runs at."""
    morning = datetime.combine(NOW.date() - timedelta(days=day), time(9 + n % 3), tzinfo=UTC)
    return (NOW - morning).total_seconds() / 3600


def a_day_of_mail(tmp_path, **watch):
    items = []
    for day, count in enumerate(PER_DAY):
        items += [unplaced(f"{day}-{n}", hours=_hours_back(day + 1, n)) for n in range(count)]
    ws, cfg, store = make(tmp_path, items, **watch)
    read(ws, store)
    return ws, cfg, store


def cost(ws, store, cfg):
    return sorting_cost.cost_of_a_day(ws, store, cfg, Router(cfg, store, env={}), NOW)


def priced(cfg, flat=False):
    cfg.ai.providers["stub"].flat_rate = flat
    cfg.ai.prices["stub/default"] = Price(input_per_million=3.0, output_per_million=6.0)


def test_a_priced_accounts_day_is_the_median_count_times_the_measured_packet_at_the_tables_price(tmp_path):
    ws, cfg, store = a_day_of_mail(tmp_path)
    priced(cfg)
    found = cost(ws, store, cfg)
    count = statistics.median(PER_DAY)
    assert (found.kind, found.messages, found.runs, found.measured) == ("money", count, 1, True)
    fixed, each = sorting_cost.tokens_per_run(ws, cfg, sorting_cost.read_mail(ws, store, cfg, NOW)[1], store.read())
    reading = fixed + each * count
    writing = OUTPUT_TOKENS_PER_MESSAGE * count + 20
    assert found.estimate_usd == pytest.approx((reading * 3.0 + writing * 6.0) / 1e6)
    # The measured size is the real packet's: the packet built for these messages reads about as many tokens.
    headers = sorting_cost.read_mail(ws, store, cfg, NOW)[1][: int(count)]
    task, _ = build_task(ws, cfg, headers, store.read())
    assert abs(estimate_tokens(task.size) - reading) <= 0.1 * reading


def test_a_day_over_one_batch_is_priced_run_by_run(tmp_path):
    """A day of 6 messages is one run in batches of 6 and two in batches of 3; the second run pays the fixed part
    again, so it costs more."""
    ws, cfg, store = a_day_of_mail(tmp_path, sorting_batch=6)
    priced(cfg)
    one = cost(ws, store, cfg)
    cfg.watch.sorting_batch = 3
    two = cost(ws, store, cfg)
    assert (one.messages, one.runs, two.runs) == (6, 1, 2)
    assert two.estimate_usd > one.estimate_usd


def test_a_plan_shows_runs_a_day_and_no_money(tmp_path):
    ws, cfg, store = a_day_of_mail(tmp_path, sorting_batch=4)
    priced(cfg, flat=True)  # the person's own answer, a plan, wins over any price
    found = cost(ws, store, cfg)
    assert (found.kind, found.messages, found.runs, found.estimate_usd) == ("runs", 6, 2, None)


def test_an_account_with_no_known_price_shows_runs_and_says_so(tmp_path):
    ws, cfg, store = a_day_of_mail(tmp_path)
    cfg.ai.providers["stub"].flat_rate = False
    found = cost(ws, store, cfg)
    assert (found.kind, found.runs, found.estimate_usd) == ("unknown", 1, None)


def test_with_no_account_for_the_work_the_figure_is_none(tmp_path):
    ws, cfg, store = a_day_of_mail(tmp_path)
    cfg.ai.tiers["routine"].use = ""
    assert cost(ws, store, cfg).kind == "none"


def test_before_any_mail_is_read_the_typical_day_is_the_setting(tmp_path):
    ws, cfg, store = make(tmp_path, [], sorting_typical_day=40, sorting_batch=25)
    found = cost(ws, store, cfg)
    assert (found.messages, found.runs, found.measured) == (40, 2, False)


def test_mail_older_than_the_window_does_not_count(tmp_path):
    ws, cfg, store = make(tmp_path, [unplaced(n, hours=24 * 30) for n in range(5)], sorting_typical_day=33)
    read(ws, store)
    found = cost(ws, store, cfg)
    assert (found.messages, found.measured) == (33, False)


def test_the_header_sample_is_the_newest_mail_as_the_sorting_would_see_it(tmp_path):
    ws, cfg, store = a_day_of_mail(tmp_path)
    counts, headers = sorting_cost.read_mail(ws, store, cfg, NOW)
    assert sorted(counts) == sorted(PER_DAY) and len(headers) == sum(PER_DAY)
    assert all(h.sender and h.subject for h in headers)


def test_the_route_returns_the_figure(tmp_path):
    from fastapi.testclient import TestClient

    from api.app import create_app

    ws, cfg, store = a_day_of_mail(tmp_path)
    store.close()
    created = create_app(ws, cfg, "t", start_worker=False)
    try:
        client = TestClient(created)
        client.headers["Authorization"] = "Bearer t"
        body = client.get(cfg.server.base_path.rstrip("/") + "/api/watch/sorting-cost").json()
    finally:
        created.state.store.close()
    assert body["kind"] == "runs" and body["messages"] == 6 and body["measured"] is True


# ---- what the weekly look at who the person deals with costs (S-0655) ----------------------------------------------


def week(ws, store, cfg):
    from engine import person_look

    return person_look.cost_of_a_week(ws, store, cfg, Router(cfg, store, env={}), NOW)


def priced_for_the_look(cfg, flat=False):
    priced(cfg, flat)
    for tier in cfg.ai.tiers.values():
        if tier.use and "/" in tier.use:
            cfg.ai.prices[tier.use] = Price(input_per_million=3.0, output_per_million=6.0)


def test_the_looks_cost_a_week_is_one_looks_estimate_times_the_looks_the_interval_makes(tmp_path):
    ws, cfg, store = make(tmp_path, [])
    priced_for_the_look(cfg)
    cfg.dispatch.knowledge.person_look_every_days = 7
    weekly = week(ws, store, cfg)
    assert weekly.kind == "money" and weekly.per_look_usd > 0
    assert (weekly.looks_a_week, weekly.per_week_usd) == (1.0, pytest.approx(weekly.per_look_usd))
    cfg.dispatch.knowledge.person_look_every_days = 1
    daily = week(ws, store, cfg)
    assert daily.per_look_usd == pytest.approx(weekly.per_look_usd)
    assert (daily.looks_a_week, daily.per_week_usd) == (7.0, pytest.approx(weekly.per_look_usd * 7))
    cfg.dispatch.knowledge.person_look_every_days = 14
    assert week(ws, store, cfg).per_week_usd == pytest.approx(weekly.per_look_usd / 2)


def test_the_looks_cost_says_a_plan_has_no_money_and_an_unpriced_account_is_unknown_and_no_account_is_none(tmp_path):
    ws, cfg, store = make(tmp_path, [])
    priced_for_the_look(cfg, flat=True)
    assert (week(ws, store, cfg).kind, week(ws, store, cfg).per_week_usd) == ("runs", None)
    ws, cfg, store = make(tmp_path / "b", [])
    cfg.ai.providers["stub"].flat_rate = False
    assert week(ws, store, cfg).kind == "unknown"
    cfg.ai.tiers["routine"].use = ""
    for tier in cfg.ai.tiers.values():
        tier.use = ""
    assert week(ws, store, cfg).kind == "none"
