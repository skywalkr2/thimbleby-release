"""Dated facts and the reminders proposed for them (design 6.32, "What arrives", S4).

A deadline, renewal, expiry, warranty end or bill an input states with a full date is a fact that carries its day, and
the rules propose a reminder for it that waits for the person's yes. The same goes for a to-do whose day an input
labels. Names and ids come from the fixtures; the day moves with the clock each test passes in."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from engine import dated_facts, held_ask, today_queue
from engine.applier import Context, Inputs, apply_changeset, check, decline_held, release
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

# A Monday at 9:00 on the person's clock (UTC here).
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
ZONE_UTC = {"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"}
_TEST = WriteContext(actor="pm", trust="trusted", op="test.dates")
RENEWAL = date(2026, 12, 15)
WORDS = "Your plan renews on December 15, 2026."


class Clock:
    def __call__(self) -> str:
        return NOW.isoformat(timespec="seconds")


def build(tmp_path, **env):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={**ZONE_UTC, **env})
    return ws, cfg, Store(ws.db_path, cfg=cfg, clock=Clock())


@pytest.fixture
def env(tmp_path):
    ws, cfg, store = build(tmp_path)
    yield ws, cfg, store
    store.close()


def fact_op(quote=WORDS, on="2026-12-15", kind="renewal", text="The plan renews on December 15, 2026"):
    op = {"op": "fact", "text": text, "evidence": {"quote": quote}}
    if on:
        op["on"] = on
    if kind:
        op["on_kind"] = kind
    return op


def apply(env, ops, raw=WORDS, now=NOW, actor="assistant"):
    _, cfg, store = env
    cs = CHANGESET.validate_python({"ops": ops}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs("REQ-1", None, raw, "", "untrusted", cites="mail:1"),
        actor=actor,
    )
    cs_id = apply_changeset(cs, [], ctx, run=None, now=now)
    return cs_id, store.read().get("changeset", cs_id).data["ops"]


def morning(cfg, year, month, day) -> datetime:
    """The moment the person's working hours start on a day (UTC here)."""
    return datetime.combine(date(year, month, day), time.fromisoformat(cfg.steward.reminders.working_start), UTC)


def make(store, kind, **data) -> str:
    with store.transaction() as tx:
        return tx.create(kind, data, _TEST).id


def test_a_dated_fact_carries_its_day_and_a_reminder_waits_for_the_persons_yes(env):
    _, cfg, store = env
    cs_id, outcomes = apply(env, [fact_op()])
    fact_outcome, reminder = outcomes
    assert fact_outcome["status"] == "applied"
    fact_id = fact_outcome["records"][0]["id"]
    fact = store.read().get("fact", fact_id)
    assert (fact.data["on"], fact.data["on_kind"]) == (RENEWAL.isoformat(), "renewal")
    assert fact.data.get("remind_at") is None

    # The proposal is a held change of the fact, at the working morning two weeks before the day.
    assert reminder["status"] == "held" and "only you can set remind_at" in reminder["reason"]
    assert reminder["op"]["id"] == fact_id and reminder["op"]["field"] == "remind_at"
    assert datetime.fromisoformat(reminder["op"]["value"]) == morning(cfg, 2026, 12, 1)
    assert reminder["op"]["evidence"]["quote"] == WORDS
    asked = held_ask.describe(store.read(), People(store, cfg), reminder["op"])
    assert asked["ask"] == "remind" and asked["day"] == RENEWAL.isoformat() and asked["quote"] == WORDS

    # Keeping it sets the fact's reminder; leaving it sets nothing and is a signal.
    release(store, cfg, cs_id, 1)
    assert datetime.fromisoformat(str(store.read().get("fact", fact_id).data["remind_at"])) == morning(cfg, 2026, 12, 1)


def test_leaving_the_proposed_reminder_sets_none(env):
    _, _, store = env
    cs_id, outcomes = apply(env, [fact_op()])
    decline_held(store, cs_id, 1)
    assert store.read().get("fact", outcomes[0]["records"][0]["id"]).data.get("remind_at") is None
    assert [s for s in store.read().list("signal") if s.data["kind"] == "held_declined"]


@pytest.mark.parametrize(
    "kind, day, expected",
    [
        ("deadline", date(2026, 11, 20), date(2026, 11, 17)),
        ("warranty", date(2027, 3, 1), date(2027, 1, 29)),
        ("bill", date(2026, 10, 30), date(2026, 10, 27)),
        # The Sunday three days before a Wednesday falls on the Friday before it.
        ("bill", date(2026, 11, 11), date(2026, 11, 6)),
    ],
)
def test_each_kind_of_day_has_its_own_lead_and_lands_on_a_working_morning(env, kind, day, expected):
    _, cfg, _ = env
    assert dated_facts.reminder_moment(cfg, day, kind, NOW) == morning(cfg, expected.year, expected.month, expected.day)


def test_a_lead_that_has_passed_moves_to_the_next_working_morning_and_a_day_gone_gets_none(env):
    _, cfg, _ = env
    soon = NOW.date() + timedelta(days=5)
    assert dated_facts.reminder_moment(cfg, soon, "renewal", NOW) == morning(cfg, 2026, 10, 20)
    assert dated_facts.reminder_moment(cfg, NOW.date(), "renewal", NOW) is None
    assert dated_facts.reminder_moment(cfg, NOW.date() - timedelta(days=1), "renewal", NOW) is None


def test_the_setting_turns_the_offer_off_and_the_fact_is_kept_all_the_same(tmp_path):
    ws, cfg, store = build(tmp_path, COCKPIT__STEWARD__DATES__SUGGEST_REMINDERS="false")
    try:
        _, outcomes = apply((ws, cfg, store), [fact_op()])
        assert [o["status"] for o in outcomes] == ["applied"]
        assert store.read().get("fact", outcomes[0]["records"][0]["id"]).data["on"] == RENEWAL.isoformat()
    finally:
        store.close()


def day_problems(env, ops, raw=WORDS):
    """What the checks say about the answer: the day the quote doesn't state is refused here, so the answer goes back to
    the assistant once to quote it."""
    _, cfg, store = env
    cs = CHANGESET.validate_python({"ops": ops}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs("REQ-1", None, raw, "", "untrusted", cites="mail:1"),
        actor="assistant",
    )
    return [p for p in check(cs, ctx) if p.severity == "refuse"]


def test_a_quote_that_does_not_state_the_day_goes_back_and_then_keeps_the_fact_without_the_day(env):
    gone = "Your plan renews soon."
    (problem,) = day_problems(env, [fact_op(quote=gone)], raw=gone)
    assert "full date" in problem.message
    # A different day than the one written beside it is no full date either.
    assert day_problems(env, [fact_op(on="2026-12-16")])
    # After the return round the fact is kept; only the day it couldn't quote is left out (S-0718).
    _, outcomes = apply(env, [fact_op(quote=gone)], raw=gone)
    assert outcomes[0]["status"] == "applied"
    kept = env[2].read().get("fact", outcomes[0]["records"][0]["id"]).data
    assert kept.get("on") is None and kept.get("on_kind") is None


def test_a_day_stated_with_no_year_takes_the_year_a_person_would_and_no_other(env):
    quote = "Renews on December 15."
    # The day the input came is 19 October, so the next 15 December is this year's.
    _, outcomes = apply(env, [fact_op(quote=quote, on="--12-15")], raw=quote)
    assert outcomes[0]["status"] == "applied"
    assert env[2].read().get("fact", outcomes[0]["records"][0]["id"]).data["on"] == RENEWAL.isoformat()
    # The same day with the year already written is accepted when it is the year the rule gives, and refused when the
    # assistant chose another.
    _, outcomes = apply(env, [fact_op(quote=quote)], raw=quote)
    assert outcomes[0]["status"] == "applied"
    (problem,) = day_problems(env, [fact_op(quote=quote, on="2027-12-15")], raw=quote)
    assert "full date" in problem.message
    _, outcomes = apply(env, [fact_op(quote=quote, on="2027-12-15")], raw=quote)
    assert env[2].read().get("fact", outcomes[0]["records"][0]["id"]).data.get("on") is None


def test_a_to_do_and_a_fact_with_a_day_of_no_year_are_read_from_the_day_the_input_came_never_kept_as_written(env):
    _, cfg, store = env
    quote = "Your bill was due on October 5 and is paid automatically on October 20"
    todo = {
        "op": "action.add",
        "text": "Pay the bill",
        "owners": [cfg.workspace.user.person],
        "due": "--10-05",
        "past": True,
        "evidence": {"quote": "Your bill was due on October 5"},
    }
    _, outcomes = apply(env, [todo, fact_op(quote=quote, on="--10-20", kind="bill")], raw=quote)
    assert [o["status"] for o in outcomes[:2]] == ["applied", "applied"], outcomes
    # Seen on 19 October: a day the input says has passed is this year's 5 October; the next 20 October is this year's.
    assert store.read().get("action", outcomes[0]["records"][0]["id"]).data["due"] == "2026-10-05"
    assert store.read().get("fact", outcomes[1]["records"][0]["id"]).data["on"] == "2026-10-20"
    stored = repr([o for o in store.read().list("action")] + [o for o in store.read().list("fact")])
    assert "--10-" not in stored


def test_a_day_of_no_year_written_any_other_way_is_returned_never_kept(env):
    from pydantic import ValidationError

    _, cfg, store = env
    for written in ("10-05", "--10-5", "Oct 5", "--13-05", "--02-30"):
        op = {"op": "action.add", "text": "Pay", "owners": [cfg.workspace.user.person], "due": written}
        with pytest.raises(ValidationError):
            CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})


def test_a_day_without_its_kind_is_refused(env):
    _, outcomes = apply(env, [fact_op(kind=None)])
    assert outcomes[0]["status"] == "refused" and "on_kind" in outcomes[0]["reason"]


def test_the_persons_own_change_gets_no_proposal(env):
    _, outcomes = apply(env, [fact_op()], actor="pm")
    assert len(outcomes) == 1


def test_a_to_do_due_on_a_labeled_day_gets_a_held_reminder_and_one_with_another_day_gets_none(env):
    _, cfg, store = env
    person = cfg.workspace.user.person
    name = People(store, cfg).name(person)
    action = {
        "op": "action.add",
        "text": "Renew the plan before it lapses",
        "owners": [name],
        "due": RENEWAL.isoformat(),
        "evidence": {"quote": WORDS},
    }
    cs_id, outcomes = apply(env, [action])
    assert [o["status"] for o in outcomes] == ["applied", "held"]
    action_id = outcomes[0]["records"][0]["id"]
    assert outcomes[1]["op"]["kind"] == "action" and outcomes[1]["op"]["id"] == action_id
    release(store, cfg, cs_id, 1)
    assert datetime.fromisoformat(str(store.read().get("action", action_id).data["remind_at"])) == morning(
        cfg, 2026, 12, 1
    )
    other = {**action, "text": "Pay the other bill", "due": "2026-12-20"}
    _, outcomes = apply(env, [other])
    assert [o["status"] for o in outcomes] == ["applied"]


def test_a_reminder_shows_on_today_from_its_moment_until_the_day_has_passed(env):
    ws, cfg, store = env
    fact = make(
        store,
        "fact",
        text="The plan renews",
        on=RENEWAL.isoformat(),
        on_kind="renewal",
        remind_at=morning(cfg, 2026, 12, 1).isoformat(),
    )

    def kinds(now):
        return [(x.kind, x.fact) for x in today_queue.queue(ws, store, cfg, now) if x.kind == "date_reminder"]

    assert kinds(morning(cfg, 2026, 12, 1) - timedelta(minutes=1)) == []
    assert kinds(morning(cfg, 2026, 12, 1) + timedelta(minutes=30)) == [("date_reminder", fact)]
    assert kinds(datetime(2026, 12, 15, 12, 0, tzinfo=UTC)) == [("date_reminder", fact)]
    assert kinds(datetime(2026, 12, 16, 9, 0, tzinfo=UTC)) == []


def test_the_dated_fact_cases_of_both_workspaces_pass_on_their_stub_answers():
    from engine.evaluate import evaluate
    from tests.conftest import DEMO_A

    for template in (DEMO_A, DEMO_B):
        results = evaluate(template, stub=True, runs=1, env={}, only=["renewal-date-is-a-dated-fact"]).results
        assert results and all(r.passed and not r.missing and not r.forbidden for r in results), results
