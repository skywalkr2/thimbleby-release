"""An unknown price is never $0 (design 6.16, "Waiting for a go"): a run on a model whose price isn't known waits for
the person's go every time, until they give its price or say the account is flat; a flat account asks only when the
person asked it to. The accounts here are the stand-in, which is flat by what it is, so an unknown one is the stand-in
the person said is not flat (`flat_rate: false`)."""

import json
from datetime import UTC, datetime

import pytest

from engine.ai import pricing
from engine.ai.adapters.stub import set_responder
from engine.ai.router import BudgetReached, Router
from engine.ai.task import AiTask
from engine.config.schema import Price
from engine.dispatcher import UNPRICED_GO, process
from engine.intake import hand_in
from engine.setup import known_endpoints
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

HOSTED = next(e for e in known_endpoints() if e["base_url"] and not e["local"] and not e["program"])
LOCAL = next(e for e in known_endpoints() if e["local"])
NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
NOTE = "The printer says proof copies will ship on the fifth."

pytestmark = pytest.mark.usefixtures("first_window_held")


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    cfg.ai.budgets.first_go = False
    use = cfg.ai.tiers["routine"].use
    cfg.ai.prices.pop(use, None)
    cfg.ai.providers[use.partition("/")[0]].flat_rate = False  # not flat, and no price: unknown
    asked: list = []

    def answer(task):
        asked.append(task.kind)
        return json.dumps({"summary": "Nothing to do.", "ops": []})

    set_responder(answer)
    store = Store(ws.db_path)
    yield ws, cfg, store, asked, use
    store.close()
    set_responder(None)


def run(env, *, granted: bool = False):
    ws, cfg, store, *_ = env
    request = hand_in(ws, store, note="", pasted=NOTE, now=NOW).request
    if granted:
        with store.transaction() as tx:
            found = tx.get("request", request)
            tx.update("request", request, {"approval": "granted"}, _who(), read_version=found.version)
    process(ws, store, cfg, Router(cfg, store, env={}), request, now=NOW)
    return store.read().get("request", request).data


def _who():
    from engine.storage import WriteContext

    return WriteContext(actor="pm", trust="trusted", op="test.unknown_price")


def test_a_run_on_a_model_with_no_known_price_waits_for_a_go_and_never_runs_unasked(env):
    data = run(env)
    assert (data["state"], data["approval"], data["waiting"]) == ("needs_you", "required", UNPRICED_GO)
    assert env[3] == [] and not env[2].read().has("run")
    assert "isn't known" in UNPRICED_GO  # the words say the price is unknown, not that it can't be estimated


def test_it_waits_again_for_the_next_one_and_runs_once_the_person_says_go(env):
    assert run(env)["approval"] == "required"
    assert run(env)["approval"] == "required"  # a go is for the run it was given on, never for the next
    data = run(env, granted=True)
    assert data["state"] != "needs_you" and env[3] == ["notes"]


def test_giving_the_model_a_price_lets_it_run_under_the_amount_to_ask_above(env):
    ws, cfg, store, asked, use = env
    cfg.ai.prices[use] = Price(input_per_million=0.01, output_per_million=0.01)
    assert run(env)["state"] != "needs_you" and asked == ["notes"]


def test_saying_the_account_is_flat_lets_it_run_and_confirm_unpriced_asks_again(env):
    ws, cfg, store, asked, use = env
    cfg.ai.providers[use.partition("/")[0]].flat_rate = True
    assert run(env)["state"] != "needs_you" and asked == ["notes"]
    cfg.ai.budgets.confirm_unpriced = True  # the person asked to be asked about flat accounts too
    assert run(env)["waiting"] == UNPRICED_GO and asked == ["notes"]


def test_a_priced_model_is_never_held_for_want_of_a_price(env):
    ws, cfg, store, asked, use = env
    cfg.ai.budgets.confirm_unpriced = True
    cfg.ai.prices[use] = Price(input_per_million=0.01, output_per_million=0.01)
    assert run(env)["state"] != "needs_you"


def test_the_router_never_calls_an_unknown_priced_account_without_a_go_but_calls_a_flat_one(env):
    ws, cfg, store, asked, use = env
    router = Router(cfg, store, env={})
    task = AiTask(kind="notes", instructions="i", stable="y", request="x", output_schema={})
    with pytest.raises(BudgetReached, match="price isn't known"):
        router.call(task, request_id=None, spend_limit=1.0, unpriced_ok=False)
    assert router.price_state(task) == pricing.UNKNOWN
    router.call(task, request_id=None, spend_limit=1.0, unpriced_ok=True)  # a go was given for it
    cfg.ai.providers[use.partition("/")[0]].flat_rate = True
    assert router.price_state(task) == pricing.FLAT
    router.call(task, request_id=None, spend_limit=1.0, unpriced_ok=False)


def test_what_makes_an_account_flat(env):
    ws, cfg, store, asked, use = env
    name = use.partition("/")[0]
    provider = cfg.ai.providers[name]
    provider.flat_rate = None
    assert pricing.is_flat(cfg, name)  # the stand-in is flat by what it is
    provider.adapter = "cli-agent"
    assert pricing.is_flat(cfg, name)
    provider.adapter, provider.kind = HOSTED["adapter"], LOCAL["id"]
    assert pricing.is_flat(cfg, name)  # a server on this computer, by its kind in the catalog
    provider.kind = HOSTED["id"]
    assert not pricing.is_flat(cfg, name)
    provider.flat_rate = True
    assert pricing.is_flat(cfg, name)
    assert not pricing.is_flat(cfg, "no-such-account")
    assert pricing.go_needed(cfg, pricing.UNKNOWN) and not pricing.go_needed(cfg, pricing.FLAT)
    assert not pricing.go_needed(cfg, pricing.PRICED) and not pricing.go_needed(cfg, None)
    cfg.ai.budgets.confirm_unpriced = True
    assert pricing.go_needed(cfg, pricing.FLAT) and not pricing.go_needed(cfg, pricing.PRICED)
    assert not pricing.allowed_without_price(cfg, pricing.FLAT, False) and pricing.allowed_without_price(
        cfg, pricing.FLAT, True
    )


def test_an_intake_on_an_unknown_priced_account_waits_for_one_go_even_when_unpriced_runs_need_none(tmp_path):
    from tests.test_source_intake import NOW as INTAKE_NOW
    from tests.test_source_intake import item, mail, make

    ws, cfg, store = make(tmp_path, [mail("new", 2), item("page")], price=None, confirm_unpriced=False)
    try:
        from engine import source_intake
        from engine.today_queue import queue
        from engine.watch import refresh

        cfg.ai.providers[cfg.ai.tiers["routine"].use.partition("/")[0]].flat_rate = False
        refresh(ws, store, cfg, "m", INTAKE_NOW)
        (line,) = [x for x in queue(ws, store, cfg, INTAKE_NOW) if x.kind == "intake_go"]
        assert line.count == 2 and line.estimate_usd is None
        assert {r.data["state"] for r in source_intake.waiting(store.read(), "m")} == {"needs_you"}
    finally:
        store.close()
