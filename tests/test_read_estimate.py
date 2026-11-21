"""What a big read's estimate counts (S-0639): the header sorting for every message, the full read of only the share
the sorting keeps (counted from the mail already sorted, with a setting before any is known), and the account's cached
price for the repeated part of each packet; and the most it could cost, with every message read at the full price."""

from __future__ import annotations

import pytest

from engine import read_estimate, sorting_cost
from engine.ai.calibration import estimate_tokens
from engine.ai.router import Router, RunPrice
from engine.config.schema import Price
from engine.dispatcher import run_price_request
from engine.mail_sorting import _tier_of, build_task
from engine.storage import WriteContext
from tests.test_mail_sorting import make, read, unplaced
from tests.test_set_aside import NOW

_CTX = WriteContext(actor="pm", trust="trusted", op="test.read-estimate")
SORTED = 20  # messages the fixture's sorting has answered for: two batches of ten
COUNT = 1700


def sorted_source(tmp_path, kept: int, cached: float | None = 0.1, **watch):
    """A source whose first `SORTED` messages were sorted: `kept` of them kept, the rest set aside by the assistant.
    The account's input costs 1.0 a million, its output 5.0 and its cached input `cached`."""
    items = [unplaced(n, hours=24 + n) for n in range(SORTED)]
    ws, cfg, store = make(tmp_path, items, sorting_batch=10, **watch)
    read(ws, store)
    cfg.ai.prices["stub/default"] = Price(
        input_per_million=1.0, output_per_million=5.0, cached_input_per_million=cached
    )
    view = store.read()
    snaps = {s.data["key"]: s for s in view.list("snapshot")}
    with store.transaction() as tx:
        for number, req in enumerate(view.list("request")):
            current = tx.get("request", req.id)
            changes: dict = {"intake": "m"}
            if number >= kept:
                mark = {"by": "assistant", "section": "sales", "rule": "The assistant's sorting"}
                changes["set_aside"] = mark
                key = store.read().get("source", req.data["source"]).data["watched"]["key"]
                shot = tx.get("snapshot", snaps[key].id)
                tx.update("snapshot", shot.id, {"set_aside": mark}, _CTX, read_version=shot.version)
            tx.update("request", req.id, changes, _CTX, read_version=current.version)
    return ws, cfg, store


def test_the_kept_share_is_counted_from_the_sorted_mail_and_a_setting_stands_in_until_a_batch_is_known(tmp_path):
    ws, cfg, store = sorted_source(tmp_path, kept=6)
    assert read_estimate.kept_share(store, cfg, "m") == pytest.approx(6 / SORTED)
    cfg.watch.sorting_batch = SORTED + 1  # fewer sorted messages than one batch: nothing is known yet
    cfg.watch.estimate_kept_share = 0.8
    assert read_estimate.kept_share(store, cfg, "m") == 0.8


def figures(ws, store, cfg):
    """The parts the estimate is built from, priced by the router itself."""
    router = Router(cfg, store, env={})
    _per_day, headers = sorting_cost.read_mail(ws, store, cfg, NOW)
    batch = [headers[n % len(headers)] for n in range(cfg.watch.sorting_batch)]
    task, _ = build_task(ws, cfg, batch, store.read())
    sorting = router.run_price(task, tier=_tier_of(cfg, task, "internal"), data_level="internal")
    request = next(r for r in store.read().list("request") if r.data.get("intake") == "m")
    reading = run_price_request(ws, store, cfg, router, request.id, NOW)
    return router, task, sorting, reading


def test_a_big_read_is_the_sorting_for_all_plus_the_kept_share_read_with_the_cache_and_the_most_has_neither(tmp_path):
    ws, cfg, store = sorted_source(tmp_path, kept=6)  # 30% kept; AI sorting in batches of 10; cached at a tenth
    router, task, sorting, reading = figures(ws, store, cfg)
    # The cache charges the stable part of the packet at a tenth of the input price.
    stable = estimate_tokens(len(task.instructions) + len(task.stable))
    assert sorting.warm == pytest.approx(sorting.full - stable * 0.9 / 1e6)
    assert reading.warm < reading.full and sorting.warm < sorting.full
    cost = read_estimate.cost_of_reading(ws, store, cfg, cfg.watch.sources[0], COUNT, NOW, router)
    batches, kept = COUNT // 10, COUNT * 0.3
    assert cost.at_most == pytest.approx(batches * sorting.full + COUNT * reading.full, abs=1e-4)
    likely = sorting.full + (batches - 1) * sorting.warm + reading.full + (kept - 1) * reading.warm
    assert cost.likely == pytest.approx(likely, abs=1e-4)
    assert cost.likely < cost.at_most and cost.unpriced == 0


def test_a_rules_only_source_has_no_sorting_price(tmp_path):
    ws, cfg, store = sorted_source(tmp_path, kept=6)
    router, _task, _sorting, reading = figures(ws, store, cfg)
    cfg.watch.sorting = "rules"
    assert read_estimate.sorting_range(ws, store, cfg, router, cfg.watch.sources[0], COUNT, NOW) == (0.0, 0.0, 0)
    cost = read_estimate.cost_of_reading(ws, store, cfg, cfg.watch.sources[0], COUNT, NOW, router)
    assert cost.at_most == pytest.approx(COUNT * reading.full, abs=1e-4)


def test_an_account_with_no_cached_price_and_nothing_set_aside_has_the_same_figure_for_both(tmp_path):
    ws, cfg, store = sorted_source(tmp_path, kept=SORTED, cached=None)
    router, _task, sorting, reading = figures(ws, store, cfg)
    assert sorting.warm == sorting.full and reading.warm == reading.full
    assert RunPrice(2.0, 2.0).runs(5) == (10.0, 10.0)
    cost = read_estimate.cost_of_reading(ws, store, cfg, cfg.watch.sources[0], COUNT, NOW, router)
    assert cost.likely == pytest.approx(cost.at_most, abs=1e-4) and cost.at_most > 0


def test_a_source_with_no_earlier_request_to_price_a_read_from_counts_only_the_sorting_and_says_the_read_is_unpriced(
    tmp_path,
):
    ws, cfg, store = make(tmp_path, [], sorting_batch=10)
    cfg.ai.prices["stub/default"] = Price(input_per_million=1.0, output_per_million=5.0)
    router = Router(cfg, store, env={})
    cost = read_estimate.cost_of_reading(ws, store, cfg, cfg.watch.sources[0], COUNT, NOW, router)
    sorting = read_estimate.sorting_range(ws, store, cfg, router, cfg.watch.sources[0], COUNT, NOW)
    assert (
        cost.unpriced == COUNT
        and cost.likely == pytest.approx(sorting[0], abs=1e-4)
        and cost.at_most == pytest.approx(sorting[1], abs=1e-4)
    )


@pytest.mark.usefixtures("first_window_held")  # the go path, as a look further back still takes it
def test_the_go_for_a_source_shows_the_held_runs_as_the_most_and_a_cheaper_likely_figure_with_the_cache(tmp_path):
    from engine import source_intake
    from tests.test_source_intake import NOW as INTAKE_NOW
    from tests.test_source_intake import mail as intake_mail
    from tests.test_source_intake import make as make_intake

    ws, cfg, store = make_intake(tmp_path, [intake_mail(f"k{n}", 2 + n) for n in range(6)], price=1.0, confirm=0.0)
    cfg.ai.prices[cfg.ai.tiers["routine"].use] = Price(
        input_per_million=1.0, output_per_million=1.0, cached_input_per_million=0.1
    )
    from engine.watch import refresh

    refresh(ws, store, cfg, "m", INTAKE_NOW)
    held = source_intake.waiting(store.read(), "m")
    assert held
    cost = source_intake.waiting_cost(ws, store, cfg, "m")
    assert cost.count == len(held)
    assert cost.at_most == pytest.approx(sum(r.data["estimate_usd"] for r in held), abs=1e-4)
    assert cost.likely < cost.at_most


@pytest.mark.usefixtures("first_window_held")  # the go path, as a look further back still takes it
def test_a_go_whose_likely_figure_is_under_the_amount_but_whose_most_is_over_still_waits_for_the_person(tmp_path):
    # The configured amount is a ceiling on what starts unasked: it is weighed against the most a go could cost.
    from engine import source_intake
    from engine.watch import refresh
    from tests.test_source_intake import NOW as INTAKE_NOW
    from tests.test_source_intake import mail as intake_mail
    from tests.test_source_intake import make as make_intake

    def world(path, confirm):
        ws, cfg, store = make_intake(path, [intake_mail(f"k{n}", 2 + n) for n in range(6)], price=1.0, confirm=confirm)
        cfg.ai.prices[cfg.ai.tiers["routine"].use] = Price(
            input_per_million=1.0, output_per_million=1.0, cached_input_per_million=0.1
        )
        refresh(ws, store, cfg, "m", INTAKE_NOW)
        return ws, cfg, store

    ws, cfg, store = world(tmp_path / "measure", 0.0)
    try:
        cost = source_intake.waiting_cost(ws, store, cfg, "m")
    finally:
        store.close()
    assert cost.likely < cost.at_most
    ws, cfg, store = world(tmp_path / "between", (cost.likely + cost.at_most) / 2)
    try:
        held = source_intake.waiting(store.read(), "m")
        assert len(held) == cost.count and all(source_intake.waits_on_go(r.data) for r in held)
    finally:
        store.close()


def test_the_most_counts_the_cache_hits_the_accounts_recorded_runs_show_and_is_as_before_with_no_history(tmp_path):
    ws, cfg, store = sorted_source(tmp_path, kept=6)
    router, task, sorting, _reading = figures(ws, store, cfg)
    assert sorting.seen == 0.0  # no recorded runs with a token count: the ceiling is the no-cache figure
    assert sorting.runs(10)[1] == pytest.approx(10 * sorting.full)
    choice = router.account_for(task, tier=_tier_of(cfg, task, "internal"), data_level="internal")
    with store.transaction() as tx:  # four recorded runs, three of them served from the cache
        for n in range(4):
            tx.create(
                "run",
                {
                    "task": task.kind,
                    "provider": choice.provider,
                    "model": choice.model_id,
                    "tier": choice.tier,
                    "started_at": NOW.isoformat(),
                    "input_tokens": 1000,
                    "output_tokens": 10,
                    "cached_input_tokens": 800 if n else 0,
                    "outcome": "ok",
                },
                _CTX,
            )
    seen = Router(cfg, store, env={}).run_price(task, tier=choice.tier, data_level="internal")
    assert seen.seen == pytest.approx(0.75)
    likely, at_most = seen.runs(10)
    assert likely < at_most < 10 * seen.full
    assert at_most == pytest.approx(seen.full + 9 * (seen.full - 0.75 * (seen.full - seen.warm)))
