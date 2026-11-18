"""The alpha's numbers for one person (design 6.32): days used in the first week, cost per day, corrections per day,
drafts sent as written and edited, and the time from install to a first result, each worked out here by hand from known
records on a fictional workspace, on the person's clock, with no AI. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine import alpha_measures
from engine.records import REGISTRY  # noqa: F401  (registers the record kinds)
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_publisher import START, Env

_ENGINE = WriteContext(actor="engine", trust="trusted", op="test.alpha-measures")
_UTC = UTC


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, DEMO_B)
    yield e
    e.close()


def at(day: int, hour: int = 9, minute: int = 0) -> datetime:
    """A moment `day` days after the first record, on the clock of the test workspace (UTC)."""
    return START + timedelta(days=day, hours=hour - 9, minutes=minute)


def run(env: Env, when: datetime, cost: float | None, outcome: str = "ok", request: str | None = None) -> str:
    with env.store.transaction() as tx:
        return tx.create(
            "run",
            {
                "request": request,
                "task": "extract",
                "provider": "p",
                "model": "m",
                "tier": "t",
                "outcome": outcome,
                "cost_usd": cost,
                "started_at": when.isoformat(),
            },
            _ENGINE,
        ).id


def signal(env: Env, kind: str, when: datetime, note: str | None = None) -> None:
    with env.store.transaction() as tx:
        tx.create("signal", {"kind": kind, "at": when.isoformat(), "note": note}, _ENGINE)


def request_seen(env: Env, ready_after: timedelta, outcome: str = "ok") -> str:
    """A request the assistant answered: queued now, with a run, and in review `ready_after` later."""
    with env.store.transaction() as tx:
        req = tx.create("request", {"task": "extract", "origin": "pm", "created_at": env.clock.text()}, _ENGINE)
    run(env, env.clock.at, 0.1, outcome, request=req.id)
    env.clock.at += ready_after
    with env.store.transaction() as tx:
        tx.update("request", req.id, {"state": "review"}, _ENGINE, read_version=req.version)
    return req.id


def assistant_draft(env: Env, *, edit: bool, body: str) -> str:
    act = env.draft(parts={"subject": "The proofs", "body": body})
    with env.store.transaction() as tx:
        found = tx.get("act", act)
        tx.update("act", act, {"made_by": "assistant"}, _ENGINE, read_version=found.version)
    if edit:
        env.person_op("act.edit", act, read_version=env.store.read().get("act", act).version, parts={"body": "Edited"})
    env.yes(act)
    return act


def measure(env: Env, now: datetime):
    return alpha_measures.alpha_measures(env.store.read(), now, _UTC)


def test_each_number_is_worked_out_from_the_first_week_and_a_week_not_yet_over_says_the_days_so_far(env):
    # Day 0: the first record is the person's own; the assistant's first answer is ready 30 minutes later.
    env.clock.at = at(0, 9, 0)
    request_seen(env, timedelta(minutes=30))
    # Day 1: only a visit to a screen that looks over the assistant's work.
    env.clock.at = at(1)
    signal(env, "review_time", at(1), '{"seconds": 60}')
    # Day 2: two runs of the week cost 0.10 (above) and 0.20; two corrections and one thing that is not one.
    env.clock.at = at(2)
    env.set_address(env.ben, "changed@example.com")  # the person's own act
    run(env, at(2), 0.2)
    run(env, at(2), None)  # a run with no known price counts as nothing
    signal(env, "sent_back", at(2))
    signal(env, "undone", at(2))
    signal(env, "kept", at(2))
    # Day 3: two drafts the assistant made; the person says yes to one as written and to one after changing it.
    env.clock.at = at(3)
    assistant_draft(env, edit=False, body="Written")
    env.clock.at = at(3, 10)
    assistant_draft(env, edit=True, body="Other")

    found = measure(env, at(4, 12))
    assert (found.since, found.until) == (at(0).date(), at(4).date())
    assert (found.days_so_far, found.complete) == (5, False)
    assert found.days_used == 4  # days 0, 1, 2, 3
    assert found.cost_total == pytest.approx(0.3) and found.cost_per_day == pytest.approx(0.06)
    assert found.corrections == 2 and found.corrections_per_day == pytest.approx(0.4)
    assert (found.sent_as_written, found.sent_edited) == (1, 1)
    assert found.first_result_minutes == 30


def test_a_whole_week_counts_seven_days_and_nothing_after_it(env):
    env.clock.at = at(0)
    request_seen(env, timedelta(minutes=5))
    run(env, at(6, 23), 0.7)  # the last day of the week
    signal(env, "sent_back", at(6, 23))
    # The eighth day and later: outside the week.
    env.clock.at = at(7)
    run(env, at(7), 50.0)
    signal(env, "sent_back", at(7))
    signal(env, "undone", at(9))
    assistant_draft(env, edit=False, body="Late")

    found = measure(env, at(9))
    assert (found.days_so_far, found.complete, found.until) == (7, True, at(6).date())
    assert found.cost_total == pytest.approx(0.8)  # 0.1 on day 0 and 0.7 on day 6
    assert found.cost_per_day == pytest.approx(0.8 / 7)
    assert found.corrections == 1 and found.corrections_per_day == pytest.approx(1 / 7)
    assert (found.sent_as_written, found.sent_edited) == (0, 0)
    assert found.days_used == 1  # only day 0: the person did nothing of their own on day 6


def test_the_days_are_the_persons_own_days(env):
    # 23:30 UTC on the first day is already the next day for someone at UTC+2.
    from zoneinfo import ZoneInfo

    env.clock.at = at(0, 23, 30)
    env.set_address(env.ana, "moved@example.com")
    now = at(1, 12)
    assert alpha_measures.alpha_measures(env.store.read(), now, _UTC).days_used == 1
    assert alpha_measures.alpha_measures(env.store.read(), now, ZoneInfo("Europe/Berlin")).days_used == 2


def test_no_ai_use_costs_nothing_and_no_result_has_no_time(env):
    env.clock.at = at(1)
    found = measure(env, at(2))
    assert (found.cost_total, found.cost_per_day, found.corrections) == (0.0, 0.0, 0)
    assert found.first_result_minutes is None


def test_an_answer_that_failed_is_not_a_first_result(env):
    env.clock.at = at(0)
    request_seen(env, timedelta(minutes=5), outcome="error")
    assert measure(env, at(1)).first_result_minutes is None


def test_an_empty_workspace_has_no_week_yet(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=None, git=False)
    store = Store(ws.db_path, cfg=ws.config(env={}, flags={"storage.backups.automatic": False}))
    try:
        found = alpha_measures.alpha_measures(store.read(), datetime.now(_UTC), _UTC)
    finally:
        store.close()
    if found.first_start is None:
        assert (found.days_so_far, found.days_used, found.cost_per_day, found.first_result_minutes) == (0, 0, 0.0, None)
    else:  # initializing recorded something: the week has begun and nothing was used
        assert found.days_so_far == 1 and found.cost_total == 0.0 and found.first_result_minutes is None


def test_asking_for_the_numbers_sends_nothing_and_holds_no_name_or_record_text(tmp_path, monkeypatch):
    import json

    import httpx

    import engine.net
    from tests.test_report_send import LOCAL_FORM, TOKEN, make_client

    seen: list = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(engine.net, "TRANSPORT", httpx.MockTransport(answer))
    client, _app, _cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        got = client.get("/api/alpha-measures")
    assert got.status_code == 200 and seen == []
    body = got.json()
    assert set(body) == {
        "since",
        "until",
        "days_so_far",
        "complete",
        "days_used",
        "cost_per_day",
        "corrections_per_day",
        "sent_as_written",
        "sent_edited",
        "first_result_minutes",
    }
    assert all(not isinstance(v, str) or v[:2] == "20" for v in body.values())  # only dates are text
    assert TOKEN not in json.dumps(body)
