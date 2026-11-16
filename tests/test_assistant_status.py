"""The assistant's alive line: what GET /api/status says about the last run, today's runs by account, the queue, the
fallback order and paused accounts. Account names come from the workspace's own settings."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.ai.pauses import Pauses, pauses_path
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

TOKEN = "test-token-value"
ZONE = "Asia/Tokyo"


@pytest.fixture
def served(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    base = ws.config(env={}, flags={})
    main = next(iter(base.ai.providers))
    # A second account for the fallback order, and the person's own time zone.
    flags = {
        "workspace.user.timezone": ZONE,
        "ai.providers.second": {"adapter": "stub", "models": {"default": "scripted"}},
        "ai.tiers.routine.fallback": ["second/default"],
    }
    cfg = ws.config(env={}, flags=flags)
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, app.state.store, main


def add_run(store, provider: str, when: datetime, outcome: str = "ok", error_kind: str | None = None) -> None:
    run = {
        "task": "notes",
        "provider": provider,
        "model": "m",
        "tier": "routine",
        "outcome": outcome,
        "error_kind": error_kind,
        "started_at": when.isoformat(),
    }
    with store.transaction() as tx:
        tx.create("run", run, WriteContext("engine", "trusted", "test"))


def assistant(client) -> dict:
    return client.get("/api/status").json()["assistant"]


def test_before_any_run_there_is_no_last_run_and_nothing_waits(served):
    client, _, main = served
    alive = assistant(client)
    assert alive["last_run_at"] is None and alive["last_run_failed"] is False
    assert alive["runs_today"] == [] and alive["queued"] == 0 and alive["oldest_queued_since"] is None
    assert alive["paused"] == []
    assert {"tier": "routine", "accounts": [main, "second"]} in alive["chains"]


def test_todays_runs_count_by_account_and_the_last_run_is_on_the_persons_clock(served):
    client, store, main = served
    now = datetime.now(UTC)
    add_run(store, main, now - timedelta(days=3))
    add_run(store, main, now - timedelta(seconds=3))
    add_run(store, "second", now - timedelta(seconds=2), outcome="invalid_output")
    add_run(store, "second", now - timedelta(seconds=1), outcome="error", error_kind="provider_down")
    # A call that found no network never reached the account: it is in no count and is not the last run.
    add_run(store, main, now, outcome="error", error_kind="offline")
    alive = assistant(client)
    assert {r["account"]: (r["count"], r["failed"]) for r in alive["runs_today"]} == {main: (1, 0), "second": (2, 2)}
    last = datetime.fromisoformat(alive["last_run_at"])
    assert last.utcoffset() == timedelta(hours=9)
    assert abs(last - (now - timedelta(seconds=1))) < timedelta(seconds=1)
    assert alive["last_run_failed"] is True


def test_an_old_last_run_is_still_the_last_run_but_not_a_run_today(served):
    client, store, main = served
    add_run(store, main, datetime.now(UTC) - timedelta(days=3))
    alive = assistant(client)
    assert alive["runs_today"] == [] and alive["last_run_at"] is not None and alive["last_run_failed"] is False


def test_the_queue_counts_requests_waiting_and_says_since_when(served):
    client, _, _ = served
    client.post("/api/handin", json={"note": "remember the reading series"})
    alive = assistant(client)
    assert alive["queued"] == 1
    assert datetime.fromisoformat(alive["oldest_queued_since"]).utcoffset() == timedelta(hours=9)


def test_a_failed_last_run_on_a_paused_account_is_a_pause_not_a_failure(served):
    client, store, main = served
    add_run(store, main, datetime.now(UTC), outcome="error", error_kind="rate_limited")
    assert assistant(client)["last_run_failed"] is True
    until = datetime.now(UTC) + timedelta(hours=1)
    Pauses(pauses_path(store)).pause(main, until)
    alive = assistant(client)
    assert alive["last_run_failed"] is False
    assert [p["account"] for p in alive["paused"]] == [main]
    assert datetime.fromisoformat(alive["paused"][0]["until"]).utcoffset() == timedelta(hours=9)


def run_now(store, request_id: str) -> None:
    from engine.dispatcher import _set

    _set(store, request_id, state="running", waiting="With the assistant now")


def test_nothing_is_being_worked_on_while_nothing_runs(served):
    client, _, _ = served
    client.post("/api/handin", json={"note": "remember the reading series"})
    alive = assistant(client)
    assert alive["working_on"] is None and alive["working_count"] == 0


def test_running_work_is_named_by_one_plain_word_with_its_count_and_the_rest_still_queued(served):
    client, store, _ = served
    for note in ("remember the reading series", "call the printer", "plan the launch"):
        client.post("/api/handin", json={"note": note})
    queued = [r.id for r in store.read().find("request", {"state": "queued"})]
    for request_id in queued[:2]:
        run_now(store, request_id)
    alive = assistant(client)
    assert alive["working_on"] == "reading" and alive["working_count"] == 2
    assert alive["queued"] == 1


def test_work_that_finished_is_no_longer_working_on(served):
    client, store, _ = served
    client.post("/api/handin", json={"note": "remember the reading series"})
    request_id = store.read().find("request", {"state": "queued"})[0].id
    run_now(store, request_id)
    assert assistant(client)["working_on"] == "reading"
    from engine.dispatcher import _set

    _set(store, request_id, state="done")
    assert assistant(client)["working_on"] is None


def test_the_held_route_says_how_many_wait_and_when_with_none_held_on_a_fresh_workspace(served):
    client, _, _ = served
    held = client.get("/api/today/held").json()
    assert held == {"count": 0, "until": None}
