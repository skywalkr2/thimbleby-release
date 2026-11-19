"""The spending boundary (design 6.16): every paid call is admitted against the daily, monthly and per-kind limits
with its estimate and the running calls' estimates held, and is recorded with a cost. Each test is a sequence in which
a call used to start or go uncounted. Account settings come from tests/fixtures/ai/ai.yaml."""

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from engine import transcribe
from engine.ai import measure, spending
from engine.ai.adapters import ADAPTERS
from engine.ai.adapters.stub import set_responder
from engine.ai.router import BudgetReached, Router
from engine.ai.smoke import CHECK_TASK, smoke_test
from engine.ai.task import AiTask
from engine.storage import WriteContext
from tests import test_capture
from tests.test_ai import KEYS, NOW, NoCatalog, cfg, host, ok_body, router_with, store  # noqa: F401

LIMIT = 2.0
SPENT = 1.95


@pytest.fixture(autouse=True)
def _nothing_left_held(store):  # noqa: F811
    yield
    assert spending.held(store) == [], "a call that ended left its amount held"


def limits(cfg, **more):  # noqa: F811
    """The test accounts with a daily ceiling of `LIMIT`, one account in line, and a price that makes a run's
    estimate exactly what its `expected_output` says: two dollars per million tokens written, nothing to read."""
    cfg.ai.budgets.per_day_usd, cfg.ai.budgets.per_month_usd = LIMIT, 30.0
    cfg.ai.tiers["routine"].fallback = []
    price = cfg.ai.prices["main/small"]
    price.input_per_million, price.output_per_million = 0.0, 2.0
    for key, value in more.items():
        setattr(cfg.ai.budgets, key, value)
    return cfg


def task(usd):
    """A run estimated at `usd` on the test price."""
    return AiTask("notes", "Do it.", "Reference.", "Input.", {}, expected_output=round(usd / 2.0 * 1e6))


def spend(store, usd, kind="notes", at=NOW):  # noqa: F811
    run = {
        "request": None,
        "task": kind,
        "provider": "main",
        "model": "m",
        "tier": "routine",
        "cost_usd": usd,
        "outcome": "ok",
        "started_at": at.isoformat(),
    }
    with store.transaction() as tx:
        tx.create("run", run, WriteContext("engine", "trusted", "test"))


def runs(store, kind=None):  # noqa: F811
    return [r.data for r in store.read().list("run") if kind is None or r.data["task"] == kind]


def answer(request):
    return httpx.Response(200, json=ok_body())


# ---- admission: the limits are ceilings ------------------------------------------------------------------------------


def test_a_call_whose_estimate_would_pass_the_daily_limit_is_refused(cfg, store):  # noqa: F811
    spend(store, SPENT)
    router, seen = router_with(limits(cfg), store, {"main": answer})
    with pytest.raises(BudgetReached, match="today") as refused:
        router.call(task(0.08), request_id="REQ-1")
    assert refused.value.period == "day"
    assert seen == [], "nothing is sent for a call the limit has no room for"
    assert len(runs(store)) == 1, "a refused call is no run"
    # A call that fits in what is left still runs.
    router.call(task(0.04), request_id="REQ-2")
    assert len(seen) == 1


def test_a_call_whose_estimate_would_pass_the_months_or_its_kinds_limit_is_refused(cfg, store):  # noqa: F811
    from engine.config.schema import TaskBudget

    spend(store, SPENT, at=NOW - timedelta(days=2))
    router, seen = router_with(limits(cfg, per_day_usd=1.0, per_month_usd=LIMIT), store, {"main": answer})
    with pytest.raises(BudgetReached, match="this month") as refused:
        router.call(task(0.08), request_id="REQ-1")
    assert refused.value.period == "month" and seen == []
    cfg.ai.budgets.per_month_usd = 30.0
    cfg.ai.budgets.per_task["notes"] = TaskBudget(per_day_usd=0.05)
    with pytest.raises(BudgetReached, match="this kind of work"):
        router.call(task(0.08), request_id="REQ-2")
    assert seen == []


def test_two_callers_at_the_edge_of_the_limit_only_one_is_admitted(cfg, store):  # noqa: F811
    spend(store, SPENT)
    limits(cfg)
    inside, go = threading.Event(), threading.Event()

    def slow(request):
        inside.set()
        assert go.wait(30)
        return httpx.Response(200, json=ok_body())

    first, seen = router_with(cfg, store, {"main": slow})
    second, also_seen = router_with(cfg, store, {"main": answer})  # another router on the same workspace
    done = []
    caller = threading.Thread(target=lambda: done.append(first.call(task(0.04), request_id="REQ-1")))
    caller.start()
    try:
        assert inside.wait(30)
        # The first call is running with its estimate held: the totals count it, and a second call has no room.
        assert second.spent()[0] == pytest.approx(SPENT + 0.04)
        with pytest.raises(BudgetReached):
            second.call(task(0.04), request_id="REQ-2")
        assert also_seen == []
    finally:
        go.set()
        caller.join(30)
    assert len(done) == 1 and len(seen) == 1
    # The held amount was settled to what the call really cost, so a call that now fits is admitted.
    real = (500 * 2.0) / 1e6
    assert second.spent()[0] == pytest.approx(SPENT + real)
    second.call(task(0.04), request_id="REQ-3")
    assert len(also_seen) == 1


def test_a_paced_retry_is_admitted_again_and_refused_once_the_limit_is_used(cfg, store):  # noqa: F811
    limits(cfg)
    replies = iter([httpx.Response(429, headers={"retry-after": "2"}), httpx.Response(200, json=ok_body())])
    router, seen = router_with(cfg, store, {"main": lambda r: next(replies)})
    # While the call waits as the account asked, other work uses up the day's limit.
    router.sleep = lambda seconds: spend(store, SPENT)
    with pytest.raises(BudgetReached, match="today"):
        router.call(task(0.08), request_id="REQ-1")
    assert len(seen) == 1, "the try after the wait is never sent"
    (waited,) = [r for r in runs(store) if r["error_kind"] == "rate_limited"]
    assert waited["cost_usd"] is None, "a request to wait is charged nothing"


# ---- a call with no answer -------------------------------------------------------------------------------------------


def test_a_timeout_after_the_call_was_sent_counts_its_estimate(cfg, store):  # noqa: F811
    def times_out(request):
        raise httpx.ReadTimeout("no answer", request=request)

    router, seen = router_with(limits(cfg), store, {"main": times_out})
    with pytest.raises(Exception, match="timeout"):
        router.call(task(0.08), request_id="REQ-1")
    (run,) = runs(store)
    assert len(seen) == 1 and run["outcome"] == "error" and run["error_kind"] == "timeout"
    assert run["cost_usd"] == pytest.approx(0.08) and run["cost_basis"] == spending.MAYBE_CHARGED
    assert router.spent() == pytest.approx((0.08, 0.08))
    from engine.usage import spend as status

    shown = status(store, cfg, NOW)
    assert shown.today_usd == pytest.approx(0.08) and shown.maybe_today_usd == pytest.approx(0.08)


def test_a_connection_lost_after_it_was_made_counts_its_estimate(cfg, store):  # noqa: F811
    def drops(request):
        raise httpx.RemoteProtocolError("the server hung up", request=request)

    router, _ = router_with(limits(cfg), store, {"main": drops})
    with pytest.raises(Exception, match="provider_down"):
        router.call(task(0.08), request_id="REQ-1")
    (run,) = runs(store)
    assert run["cost_usd"] == pytest.approx(0.08) and run["cost_basis"] == spending.MAYBE_CHARGED


def test_a_call_cut_off_by_sleep_counts_its_estimate_and_stays_no_work(cfg, store):  # noqa: F811
    from engine.dispatcher import request_spent

    limits(cfg)
    clock = {"now": NOW}

    def cut_off(request):
        clock["now"] = NOW + timedelta(seconds=cfg.dispatch.sleep_gap_seconds + 600)  # the computer slept meanwhile
        raise httpx.ReadTimeout("no answer", request=request)

    router, _ = router_with(cfg, store, {"main": cut_off})
    router.now = lambda: clock["now"]
    with pytest.raises(Exception, match="no_work"):
        router.call(task(0.08), request_id="REQ-1")
    (run,) = runs(store)
    assert run["no_work"] is True and run["error_kind"] == "no_work"
    assert run["cost_usd"] == pytest.approx(0.08) and run["cost_basis"] == spending.MAYBE_CHARGED
    assert spending.totals(store, NOW)[0] == pytest.approx(0.08), "the limits count it"
    assert request_spent(store, "REQ-1") == 0.0, "the request's own amount still leaves it out"


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("no route", request=r)), "offline"),
        (lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}), "auth"),
        (lambda r: httpx.Response(429, headers={"retry-after": "900"}), "rate_limited"),
    ],
)
def test_a_call_refused_before_anything_was_sent_counts_nothing(cfg, store, reply, kind):  # noqa: F811
    router, _ = router_with(limits(cfg), store, {"main": reply})
    with pytest.raises(Exception):  # noqa: B017, PT011 - each failure has its own error; the run says which it was
        router.call(task(0.08), request_id="REQ-1")
    (run,) = runs(store)
    assert run["error_kind"] == kind and run["cost_usd"] is None and run["cost_basis"] is None
    assert router.spent() == (0.0, 0.0)


def test_a_failure_before_a_program_could_start_counts_nothing(cfg, store):  # noqa: F811
    from engine.ai.task import AiError

    class Missing:
        def run(self, task, model):
            raise AiError("provider_down", "the program isn't installed", sent=False)

    router = Router(
        limits(cfg), store, env=KEYS, adapter_factory=lambda *a: Missing(), now=lambda: NOW, catalogs=NoCatalog()
    )
    with pytest.raises(AiError):
        router.call(task(0.08), request_id="REQ-1")
    (run,) = runs(store)
    assert run["cost_usd"] is None and run["cost_basis"] is None


# ---- the account check -----------------------------------------------------------------------------------------------


def check_factory(cfg, seen):  # noqa: F811
    def factory(name, settings, secret):
        def handle(request):
            seen.append(request.url.host)
            return httpx.Response(200, json=ok_body('{"ok": true}'))

        return ADAPTERS[name](settings, secret, transport=httpx.MockTransport(handle))

    return factory


def test_an_account_check_is_admitted_and_its_calls_are_recorded_as_runs(cfg, store):  # noqa: F811
    limits(cfg)
    seen = []
    smoke_test(cfg, KEYS, check_factory(cfg, seen), store)
    counted = runs(store, CHECK_TASK)
    on_main = [r for r in counted if r["provider"] == "main"]
    assert on_main and len(on_main) == seen.count(host(cfg, "main")), "every call that was answered is a run"
    assert all(r["tier"] == CHECK_TASK and r["request"] is None and r["outcome"] == "ok" for r in counted)
    real = (500 * 2.0) / 1e6
    assert all(r["cost_usd"] == pytest.approx(real) and r["cost_basis"] is None for r in on_main)
    assert spending.totals(store, datetime.now(UTC))[1] == pytest.approx(sum(r["cost_usd"] or 0 for r in counted))


def test_an_account_check_the_limits_have_no_room_for_sends_nothing(cfg, store):  # noqa: F811
    limits(cfg)
    spend(store, LIMIT, at=datetime.now(UTC))
    seen = []
    with pytest.raises(BudgetReached, match="today"):
        smoke_test(cfg, KEYS, check_factory(cfg, seen), store)
    assert seen == [] and runs(store, CHECK_TASK) == []


def test_an_account_check_call_that_timed_out_counts_its_estimate(cfg, store):  # noqa: F811
    limits(cfg)

    def factory(name, settings, secret):
        def handle(request):
            raise httpx.ReadTimeout("no answer", request=request)

        return ADAPTERS[name](settings, secret, transport=httpx.MockTransport(handle))

    results = smoke_test(cfg, KEYS, factory, store)
    assert any(not r.ok and r.error_kind == "timeout" for r in results)
    on_main = [r for r in runs(store, CHECK_TASK) if r["provider"] == "main"]
    assert on_main and all(r["cost_basis"] == spending.MAYBE_CHARGED and r["cost_usd"] > 0 for r in on_main)


# ---- a transcription -------------------------------------------------------------------------------------------------


def test_a_transcription_with_no_cost_in_its_answer_is_recorded_at_its_estimate(tmp_path):
    price = 0.6  # per minute of speech
    ws, cfg, store = test_capture.workspace(  # noqa: F811
        tmp_path, price=price, budgets={"confirm_above_usd": 5.0, "per_run_usd": 5.0, "per_day_usd": 5.0}
    )
    try:
        set_responder(lambda task: "Ring the dentist on Friday." if task.audio else "{}")
        request = transcribe.hand_in(store, cfg, test_capture.SOUND, name="memo.m4a", media_type="audio/mp4")
        test_capture.run(ws, cfg, store, request)
        (run,) = runs(store, transcribe.TASK)
        minutes = len(test_capture.SOUND) * 8 / (cfg.steward.capture.audio_kbps * 1000) / 60
        assert run["outcome"] == "ok" and run["cost_usd"] == pytest.approx(minutes * price)
        assert run["cost_basis"] == spending.ESTIMATED
        assert spending.totals(store, datetime.now(UTC))[0] == pytest.approx(minutes * price)
        assert spending.held(store) == []
    finally:
        set_responder(None)
        store.close()


def test_a_transcription_on_a_model_with_no_audio_price_stays_unpriced(tmp_path):
    ws, cfg, store = test_capture.workspace(tmp_path)  # noqa: F811
    try:
        set_responder(lambda task: "Ring the dentist on Friday." if task.audio else "{}")
        request = transcribe.hand_in(store, cfg, test_capture.SOUND, name="memo.m4a", media_type="audio/mp4")
        test_capture.run(ws, cfg, store, request)
        (run,) = runs(store, transcribe.TASK)
        assert run["cost_usd"] is None and run["cost_basis"] is None
    finally:
        set_responder(None)
        store.close()


# ---- measuring and the check on a switch -----------------------------------------------------------------------------


def test_a_measuring_admits_each_case_through_the_boundary(cfg, store):  # noqa: F811
    spend(store, SPENT)
    limits(cfg)
    meter = measure.Meter(store, cfg, now=lambda: NOW, per_case=0.04)
    assert meter.stops() is False
    # The case now running holds about what it costs: other work sees it, and has no room beside it.
    router, seen = router_with(cfg, store, {"main": answer})
    assert router.spent()[0] == pytest.approx(SPENT + 0.04)
    with pytest.raises(BudgetReached):
        router.call(task(0.04), request_id="REQ-1")
    assert seen == []
    meter.count(SimpleNamespace(accounts=["main/main-small"], cost_usd=0.03, seconds=1.0))
    assert spending.held(store) == [] and router.spent()[0] == pytest.approx(SPENT + 0.03)
    assert [r["cost_usd"] for r in runs(store, measure.TASK)] == [0.03]
    # About what one case costs no longer fits in what is left: the next case is not made.
    assert meter.stops() is True and meter.reason == measure.LIMIT_DAY


def test_a_measuring_with_no_plan_holds_what_its_dearest_case_cost(cfg, store):  # noqa: F811
    limits(cfg, per_day_usd=0.5)
    meter = measure.Meter(store, cfg, now=lambda: NOW)
    assert meter.stops() is False
    meter.count(SimpleNamespace(accounts=["main/main-small"], cost_usd=0.3, seconds=1.0))
    # A second case like the first would take the day past its limit, so it is not made.
    assert meter.stops() is True and meter.reason == measure.LIMIT_DAY
    assert len(runs(store, measure.TASK)) == 1
