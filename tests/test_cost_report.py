"""What a provider actually charged, kept per account and set beside the app's own figure (design 6.16, "What a provider
actually charged"; S-0654): the read fills each UTC day of an account, nothing is read without the key and the setting,
a partial read is marked, three failures in a row are a Today line, a gap shows only on a settled day narrowed to the
account's key and above both margins, and nothing about the report changes what the app limits or estimates. A
recorded fictional report plays back through a stubbed transport; nothing reaches a network."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from engine.ai import cost_report
from engine.ai.account_state import account_states
from engine.ai.adapters import ADAPTERS, make_adapter
from engine.ai.task import AiError, CostReadout, ProviderCostDay
from engine.config.schema import ProviderSettings
from engine.storage import Store, WriteContext
from engine.today_queue import queue
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

FIXTURES = Path(__file__).parent / "fixtures" / "ai"
NATIVE = yaml.safe_load((FIXTURES / "catalog-claims.yaml").read_text("utf-8"))["native_adapter"]
REPORT = json.loads((FIXTURES / "cost-report.json").read_text("utf-8"))
MODULE = importlib.import_module(ADAPTERS[NATIVE["adapter"]].__module__)
NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
WRITE = WriteContext(actor="engine", trust="trusted", op="test")
ACCOUNT = "acct"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"storage.backups.automatic": False})
    cfg.ai.providers[ACCOUNT] = ProviderSettings(
        adapter=NATIVE["adapter"],
        base_url=f"https://{MODULE.REPORT_HOST}",
        models={"default": "m"},
        billing_auth="env:BILLING",
        billing_key_id="apikey_example_one",
        cost_report_hours=4,
    )
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


class Playback:
    """A factory that gives the native adapter a stubbed transport, and counts the adapters it made."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []
        self.made = 0

    def handler(self, request):
        self.requests.append(request)
        one = self.answers.pop(0) if self.answers else {"data": [], "has_more": False}  # a window with nothing
        return one if isinstance(one, httpx.Response) else httpx.Response(200, json=one)

    def __call__(self, name, settings, secret, billing=None):
        self.made += 1
        return ADAPTERS[name](settings, secret, billing_secret=billing, transport=httpx.MockTransport(self.handler))


def day_rows(*days, amount="500"):
    return {
        "data": [{"starting_at": f"{d}T00:00:00Z", "cost": {"amount": amount, "currency": "USD"}} for d in days],
        "has_more": False,
    }


def app_run(store, day, cost, task="notes", provider=ACCOUNT, error_kind=None):
    data = {
        "task": task,
        "provider": provider,
        "model": "m",
        "tier": "routine",
        "outcome": "ok",
        "started_at": datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=10).isoformat(),
        "cost_usd": cost,
        "error_kind": error_kind,
    }
    with store.transaction() as tx:
        tx.create("run", data, WRITE)


def read_now(env, playback, now=NOW):
    ws, cfg, store = env
    return cost_report.run(ws, store, cfg, {"BILLING": "admin"}, now=now, factory=playback, sleep=lambda _: None)


def kept_day(store, text):
    return (cost_report.read(store)["accounts"][ACCOUNT]["days"])[f"{text}/USD"]


def lines(env, kind, now=NOW):
    ws, cfg, store = env
    return [x for x in queue(ws, store, cfg, now) if x.kind == kind]


# ---- the read -----------------------------------------------------------------------------------------------------


def test_a_read_fills_the_days_per_account_and_a_second_read_overwrites_them(env):
    _, _, store = env
    first = Playback(REPORT["page_one"], REPORT["page_two"])
    assert read_now(env, first) == [ACCOUNT]
    assert float(kept_day(store, "2026-11-15")["amount"]) == 412.8
    assert kept_day(store, "2026-11-15")["scope"] == "key"
    assert all("apikey_example_one" in r.url.query.decode() for r in first.requests)
    later = NOW + timedelta(hours=5)
    revised = {
        "data": [{"starting_at": "2026-11-15T00:00:00Z", "cost": {"amount": "50000", "currency": "USD"}}],
        "has_more": False,
    }
    read_now(env, Playback(revised), now=later)
    assert float(kept_day(store, "2026-11-15")["amount"]) == 500  # overwritten, not added
    assert kept_day(store, "2026-11-17")  # a day the later read didn't mention is still kept


def test_days_older_than_the_configured_window_are_dropped(env):
    _, cfg, store = env
    cfg.ai.cost_report_days = 5
    read_now(env, Playback(day_rows("2026-11-10", "2026-11-18")))
    days = cost_report.read(store)["accounts"][ACCOUNT]["days"]
    assert set(days) == {"2026-11-18/USD"}
    # the first read asked for exactly the configured window, ending today
    play = Playback(day_rows("2026-11-18"))
    read_now(env, play, now=NOW + timedelta(hours=5))
    assert play.requests[0].url.params["starting_at"] == "2026-11-15T00:00:00Z"


def test_nothing_is_read_without_the_key_and_the_setting(env):
    ws, cfg, store = env
    play = Playback(day_rows("2026-11-18"))
    cfg.ai.providers[ACCOUNT].cost_report_hours = 0
    assert cost_report.due(store, cfg, NOW) == [] and read_now(env, play) == [] and play.made == 0
    cfg.ai.providers[ACCOUNT].cost_report_hours = 4
    cfg.ai.providers[ACCOUNT].billing_auth = None
    assert cost_report.due(store, cfg, NOW) == [] and read_now(env, play) == [] and play.made == 0
    assert not play.requests


def test_the_hours_are_refused_without_the_billing_key():
    with pytest.raises(ValidationError, match="billing key"):
        ProviderSettings(adapter="stub", cost_report_hours=4)
    ProviderSettings(adapter="stub", cost_report_hours=0)  # off needs none


def test_an_account_whose_adapter_has_no_report_is_never_read(env):
    _, cfg, store = env
    cfg.ai.providers["plain"] = ProviderSettings(adapter="stub", models={"default": "m"})
    assert not cost_report.offers_report(cfg, "plain") and cost_report.offers_report(cfg, ACCOUNT)
    assert cost_report.due(store, cfg, NOW) == [ACCOUNT]


def test_it_is_read_again_only_when_the_hours_have_passed(env):
    _, cfg, store = env
    read_now(env, Playback(day_rows("2026-11-18")))
    assert cost_report.due(store, cfg, NOW + timedelta(hours=3)) == []
    assert cost_report.due(store, cfg, NOW + timedelta(hours=4)) == [ACCOUNT]


def test_a_partial_read_is_marked_partial(env):
    _, cfg, store = env
    cfg.ai.cost_report_pages = 1
    read_now(env, Playback(REPORT["page_one"]))
    assert cost_report.read(store)["accounts"][ACCOUNT]["partial"] is True


def test_a_complete_read_is_not_partial(env):
    _, _, store = env
    read_now(env, Playback(REPORT["page_one"], REPORT["page_two"]))
    assert cost_report.read(store)["accounts"][ACCOUNT]["partial"] is False


def test_a_throttle_with_a_long_wait_moves_the_next_try_out(env):
    _, cfg, store = env
    read_now(env, Playback(httpx.Response(429, headers={"retry-after": "7200"})))
    assert cost_report.read(store)["accounts"][ACCOUNT]["failed"]["kind"] == "rate_limited"
    assert cost_report.due(store, cfg, NOW + timedelta(hours=5)) == []  # the asked-for two hours came after the four
    assert cost_report.due(store, cfg, NOW + timedelta(hours=7)) == [ACCOUNT]


def test_a_missing_billing_key_is_a_failure_with_its_kind_not_a_crash(env):
    ws, cfg, store = env
    assert cost_report.run(ws, store, cfg, {}, now=NOW, factory=Playback()) == []
    assert cost_report.read(store)["accounts"][ACCOUNT]["failed"]["kind"] == "no_key"


# ---- failures on Today --------------------------------------------------------------------------------------------


def fail(env, kind_status, times, start=NOW):
    for n in range(times):
        read_now(
            env,
            Playback(httpx.Response(kind_status, json={"error": {"type": "authentication_error"}})),
            now=start + timedelta(hours=5 * n),
        )


def test_three_failed_reads_in_a_row_are_a_line_and_two_are_not(env):
    fail(env, 401, 2)
    assert lines(env, "cost_read_failed") == []
    fail(env, 401, 3)
    found = lines(env, "cost_read_failed")
    assert [(x.account, x.state) for x in found] == [(ACCOUNT, "auth")]


def test_one_good_read_clears_the_failures_and_the_line(env):
    fail(env, 401, 3)
    read_now(env, Playback(day_rows("2026-11-18")), now=NOW + timedelta(hours=40))
    assert lines(env, "cost_read_failed", NOW + timedelta(hours=40)) == []


def test_the_failure_line_goes_when_the_report_is_turned_off(env):
    _, cfg, _ = env
    fail(env, 401, 3)
    cfg.ai.providers[ACCOUNT].cost_report_hours = 0
    assert lines(env, "cost_read_failed") == []


# ---- the app's figure beside the real one ---------------------------------------------------------------------------


def test_the_app_figure_is_per_utc_day_and_split_by_kind_of_work(env):
    ws, cfg, store = env
    app_run(store, date(2026, 11, 16), 0.5, task="notes")
    app_run(store, date(2026, 11, 16), 0.25, task="mail")
    app_run(store, date(2026, 11, 16), 9, provider="other")
    app_run(store, date(2026, 11, 16), 4, error_kind="offline")  # never reached the account
    read_now(env, Playback(day_rows("2026-11-16", amount="100")))
    row = next(r for r in cost_report.compare(store, cfg, ACCOUNT, NOW) if r.day == date(2026, 11, 16))
    assert row.reported and float(row.amount) == 1.0 and row.currency == "USD"
    assert row.app_usd == pytest.approx(0.75) and row.by_task == {"notes": 0.5, "mail": 0.25}


def test_a_day_not_reported_yet_has_no_figure_never_zero(env):
    _, cfg, store = env
    app_run(store, date(2026, 11, 19), 0.5)
    read_now(env, Playback(day_rows("2026-11-18")))
    rows = {r.day: r for r in cost_report.compare(store, cfg, ACCOUNT, NOW)}
    assert rows[date(2026, 11, 19)].reported is False and rows[date(2026, 11, 19)].amount is None
    assert rows[date(2026, 11, 19)].open is True  # today: "so far"


def test_a_report_in_another_currency_is_shown_but_never_compared(env):
    _, cfg, store = env
    app_run(store, date(2026, 11, 10), 1)
    other = {
        "data": [{"starting_at": "2026-11-10T00:00:00Z", "cost": {"amount": "99999", "currency": "EUR"}}],
        "has_more": False,
    }
    read_now(env, Playback(other))
    row = next(r for r in cost_report.compare(store, cfg, ACCOUNT, NOW) if r.day == date(2026, 11, 10))
    assert row.currency == "EUR" and not row.gap


# ---- the gap -------------------------------------------------------------------------------------------------------


def gap_setup(env, real="500", app=1.0, day=date(2026, 11, 10)):
    _, _, store = env
    app_run(store, day, app)
    read_now(env, Playback(day_rows(day.isoformat(), amount=real)))


def test_a_settled_key_scoped_day_far_above_the_app_is_one_line_for_all_such_days(env):
    _, _, store = env
    gap_setup(env)
    app_run(store, date(2026, 11, 11), 1.0)
    read_now(env, Playback(day_rows("2026-11-10", "2026-11-11", amount="500")), now=NOW + timedelta(hours=5))
    found = lines(env, "cost_gap", NOW + timedelta(hours=5))
    assert len(found) == 1 and found[0].account == ACCOUNT and found[0].count == 2
    assert found[0].provider_usd == pytest.approx(10.0) and found[0].app_usd == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("real", "app", "why"),
    [
        ("500", 4.5, "above by 0.50 dollars: under the amount"),
        ("500", 4.2, "above by 0.80 dollars: under the amount"),
        ("5000", 45.0, "above by 5 dollars but under 20 percent"),
        ("100", 1.0, "equal"),
        ("50", 1.0, "below"),
    ],
)
def test_a_difference_under_either_margin_is_not_a_gap(env, real, app, why):
    gap_setup(env, real=real, app=app)
    assert lines(env, "cost_gap") == [], why


def test_the_two_margins_come_from_the_settings(env):
    _, cfg, _ = env
    gap_setup(env, real="500", app=4.5)
    cfg.ai.cost_gap_usd = 0.1
    assert lines(env, "cost_gap") == []  # 11 percent: still under the percentage
    cfg.ai.cost_gap_percent = 5
    assert len(lines(env, "cost_gap")) == 1
    cfg.ai.cost_gap_percent = 50
    assert lines(env, "cost_gap") == []


def test_a_day_not_yet_settled_is_never_a_gap(env):
    _, cfg, _ = env
    gap_setup(env, day=date(2026, 11, 17))  # two days old with the default settle of 2
    assert lines(env, "cost_gap") == []
    cfg.ai.cost_gap_settle_days = 1
    assert len(lines(env, "cost_gap")) == 1
    gap_setup(env, day=date(2026, 11, 19))  # today: never
    cfg.ai.cost_gap_settle_days = 0
    assert [x.count for x in lines(env, "cost_gap")] == [1]


def test_a_report_of_the_whole_organization_is_never_a_gap(env):
    _, cfg, _ = env
    cfg.ai.providers[ACCOUNT].billing_key_id = None
    gap_setup(env)
    assert lines(env, "cost_gap") == []
    row = cost_report.compare(env[2], cfg, ACCOUNT, NOW)[0]
    assert row.scope == "organization"


def test_not_now_is_remembered_for_those_days_and_a_new_day_brings_it_back(env):
    ws, cfg, store = env
    gap_setup(env)
    assert cost_report.not_now(store, cfg, ACCOUNT, NOW) is True
    assert lines(env, "cost_gap") == []
    app_run(store, date(2026, 11, 12), 1.0)
    read_now(env, Playback(day_rows("2026-11-10", "2026-11-12", amount="500")), now=NOW + timedelta(hours=5))
    assert len(lines(env, "cost_gap", NOW + timedelta(hours=5))) == 1
    assert cost_report.not_now(store, cfg, "nobody", NOW) is False


# ---- limits and estimates keep the app's own figure ----------------------------------------------------------------


def test_what_the_provider_charged_changes_no_figure_the_app_limits_on(env):
    ws, cfg, store = env
    app_run(store, date(2026, 11, 19), 0.5)
    before = account_states(ws, store, cfg, NOW)[ACCOUNT].spent_today_usd
    read_now(env, Playback(day_rows("2026-11-19", amount="999999")))
    assert account_states(ws, store, cfg, NOW)[ACCOUNT].spent_today_usd == before == pytest.approx(0.5)


# ---- the check made when a billing key is added --------------------------------------------------------------------


def test_adding_a_key_runs_one_small_read_and_a_refused_key_is_said_at_once(env):
    _, cfg, _ = env
    provider = cfg.ai.providers[ACCOUNT]
    ok = Playback(day_rows("2026-11-19"))
    assert cost_report.check(provider, "admin", None, now=NOW, factory=ok) is None and len(ok.requests) == 1
    refused = Playback(httpx.Response(401, json={"error": {"type": "authentication_error"}}))
    said = cost_report.check(provider, "admin", None, now=NOW, factory=refused)
    assert said == cost_report.PROBLEMS["auth"]
    proxied = provider.model_copy(update={"base_url": REPORT["proxy_base_url"]})
    unsent = Playback()
    assert cost_report.check(proxied, "admin", None, now=NOW, factory=unsent) == cost_report.PROBLEMS["other"]
    assert not unsent.requests


def test_a_gateway_address_account_is_refused_by_the_adapter_and_counts_as_a_failure(env):
    ws, cfg, store = env
    cfg.ai.providers[ACCOUNT].base_url = REPORT["proxy_base_url"]
    play = Playback()
    assert read_now(env, play) == [] and not play.requests
    assert cost_report.read(store)["accounts"][ACCOUNT]["failed"]["kind"] == "other"


def test_make_adapter_and_the_dataclasses_stay_importable_from_the_contract():
    assert make_adapter and CostReadout and ProviderCostDay and AiError


def test_a_failure_kind_the_screens_have_no_words_for_is_kept_as_other(env):
    class Odd:
        def cost_report(self, *a, **k):
            raise AiError("no_output", "nothing")

    ws, cfg, store = env
    cost_report.run(ws, store, cfg, {"BILLING": "admin"}, now=NOW, factory=lambda *a: Odd())
    assert cost_report.read(store)["accounts"][ACCOUNT]["failed"]["kind"] == "other"
