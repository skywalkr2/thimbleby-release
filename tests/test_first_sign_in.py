"""A mail account's first sign-in (S-0585, design 6.22, 6.32): once its first read has finished, one weekly look
(`knowledge-person`) is queued over what the tally holds, held for the person's go like any AI work and never run
unasked; the Mail step then asks how far back to read mail in full (three reaches, each with its estimate, none chosen),
and a chosen reach goes through the look further back, archived and deleted messages included, held for the go. Names
and days come from the fixtures; the AI is the stub."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

from engine import person_look, source_intake
from engine.ai.router import Router
from engine.config import load_config
from engine.config.schema import Price
from engine.dispatcher import process
from engine.stages import approve_stage_request
from engine.storage import Store, StoreError
from engine.watch import refresh
from tests.test_look_back_addons import FIXTURE, _manifest
from tests.test_people_suggestions import who
from tests.test_source_intake import mail
from tests.test_today_panels_jobs import workspace

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
TOKEN = "first-sign-in-token"
# The fixture's reader keeps where a message was, so a deleted one can be handed in.
KEPT_WHERE = FIXTURE.replace(
    'message=MessageDetails(sender=m.get("sender"), received=m.get("received"), unread=True),',
    'message=MessageDetails(sender=m.get("sender"), received=m.get("received"), unread=True, where=m.get("where")),',
)
assert KEPT_WHERE != FIXTURE


def from_person(key: str, who_n: int, days: float, where: str | None = None, now: datetime = NOW) -> dict:
    sender = who(who_n)
    entry = mail(key, days, now=now)
    entry["author"] = sender
    entry["message"] = {**entry["message"], "sender": sender, **({"where": where} if where else {})}
    return entry


def make(tmp_path):
    """Two mail accounts of the one add-on: the first reads three people's mail, the second another's."""
    ws, cfg, store = workspace(tmp_path, KEPT_WHERE)
    store.close()
    (ws.root / "plugins" / "p18" / "plugin.yaml").write_text(yaml.safe_dump(_manifest()))
    first = [from_person(f"a{i}-{n}", n, 1 + i % 3) for i in range(3) for n in (0, 1)]
    older = [
        from_person("o20", 0, 20),
        from_person("o21", 1, 21, where="deleted"),  # deleted by the person, still read
        from_person("o22", 0, 22, where="archived"),
        from_person("o60", 1, 60),
    ]
    second = [from_person(f"b{i}", 5, 1) for i in range(3)]
    sources = [
        {"id": "m", "connector": "p18/inbox", "label": "Inbox", "settings": {"items": first, "older": older}},
        {"id": "m2", "connector": "p18/inbox", "label": "Other inbox", "settings": {"items": second}},
    ]
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": sources, "sorting": "rules"}))
    cfg = load_config(ws.config_dir, env={})
    use = cfg.ai.tiers["routine"].use
    cfg.ai.prices[use] = Price(input_per_million=50.0, output_per_million=50.0)
    cfg.ai.budgets.confirm_above_usd = 0.10
    cfg.ai.budgets.first_go = False
    store = Store(ws.db_path, cfg=cfg)
    assert store.plugins.active("p18"), store.plugins.status["p18"].reason
    return ws, cfg, store


@pytest.fixture
def env(tmp_path):
    ws, cfg, store = make(tmp_path)
    yield ws, cfg, store
    store.close()


def run_look(ws, cfg, store, request, at=NOW):
    process(ws, store, cfg, Router(cfg, store, env={}), request, now=at)
    return store.read().get("request", request).data


def test_the_first_read_queues_one_look_that_waits_for_the_go_and_nothing_runs_without_it(env):
    ws, cfg, store = env
    assert person_look.queue(store, cfg, NOW) is None  # nothing is read yet
    refresh(ws, store, cfg, "m", NOW)
    assert person_look.queue(store, cfg, NOW) is None  # the other account's first read is not in: the look waits
    refresh(ws, store, cfg, "m2", NOW)
    request = person_look.queue(store, cfg, NOW)
    assert request is not None
    assert person_look.queue(store, cfg, NOW + timedelta(hours=1)) is None  # one at a time
    held = run_look(ws, cfg, store, request)
    assert (held["task"], held["state"], held["approval"]) == (person_look.TASK, "needs_you", "required")
    assert held["estimate_usd"] > 0 and not store.read().has("run")
    assert person_look.held_for_go(store).id == request
    assert person_look.look_state(ws, store, cfg) == "waiting"
    # The go starts it and only then does it run.
    approve_stage_request(store, request, store.read().get("request", request).version)
    done = run_look(ws, cfg, store, request)
    assert done["state"] in ("done", "review") and store.read().has("run")


def test_another_accounts_first_read_inside_the_week_brings_one_more_look_for_its_new_people_only(env):
    ws, cfg, store = env
    cfg.watch.sources[1].enabled = False  # the second account is not signed in yet
    refresh(ws, store, cfg, "m", NOW)
    first = person_look.queue(store, cfg, NOW)
    approve_look = lambda r: approve_stage_request(store, r, store.read().get("request", r).version)  # noqa: E731
    run_look(ws, cfg, store, first)
    approve_look(first)
    run_look(ws, cfg, store, first)
    assert person_look.queue(store, cfg, NOW + timedelta(days=1)) is None  # nothing new, and it is not a week
    cfg.watch.sources[1].enabled = True
    refresh(ws, store, cfg, "m2", NOW + timedelta(days=1))
    second = person_look.queue(store, cfg, NOW + timedelta(days=1))
    assert second is not None and second != first
    listed = store.read().get("request", second).data["asked_about"]
    assert listed == ["c5@example.com"]  # the people a look already read are not asked about again


def test_the_choice_offers_three_estimates_and_chooses_none(env):
    ws, cfg, store = env
    source = cfg.watch.sources[0]
    assert not source_intake.full_read_pending(store, cfg, source)  # nothing read yet
    refresh(ws, store, cfg, "m", NOW)
    assert source_intake.full_read_pending(store, cfg, source)
    options = source_intake.full_read_options(ws, store, cfg, "m", NOW)
    assert [o.days for o in options] == [14, 30, 90]
    assert options[0].count == 0 and options[0].estimate_usd is None  # the first read already covers 2 weeks
    assert options[1].count == 3 and options[1].estimate_usd > 0  # the three older messages, one deleted
    assert options[2].count == 4 and options[2].estimate_usd > options[1].estimate_usd
    run = source_intake.intake_run(store.read(), "m")
    assert run.data.get("full_read") is None and source_intake.full_read_pending(store, cfg, source)
    held = [r for r in store.read().list("request") if r.data.get("intake") == "m"]
    assert len(held) == 6  # asking made no request: only the first read's


def test_the_chosen_reach_is_read_through_the_look_further_back_deleted_and_archived_mail_included(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    done = source_intake.read_full_now(ws, store, cfg, "m", 30, NOW)
    assert done is not None and done.taken == 3 and not done.started  # held for the go like any AI work
    view = store.read()
    older = [r for r in view.list("request") if r.data.get("intake") == "m" and r.data["state"] == "needs_you"]
    assert all(source_intake.waits_on_go(r.data) for r in older)
    kept = {view.get("source", r.data["source"]).data["title"] for r in older}
    assert {"Subject of o20", "Subject of o21", "Subject of o22"} <= kept  # the deleted and archived ones among them
    assert "Subject of o60" not in kept  # beyond the reach
    assert source_intake.intake_run(view, "m").data["full_read"] == 30
    assert not source_intake.full_read_pending(store, cfg, cfg.watch.sources[0])


def test_not_now_reads_nothing_and_ends_the_question_and_a_reach_not_offered_is_refused(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    before = len(store.read().list("request"))
    assert source_intake.answer_full_read(ws, store, cfg, "m", 0, NOW) is None
    assert len(store.read().list("request")) == before
    assert not source_intake.full_read_pending(store, cfg, cfg.watch.sources[0])
    with pytest.raises(StoreError):
        source_intake.answer_full_read(ws, store, cfg, "m", 45, NOW)


def test_a_reach_the_first_read_already_covers_takes_nothing_more_and_is_answered(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    before = len(store.read().list("request"))
    assert source_intake.answer_full_read(ws, store, cfg, "m", 14, NOW) is None
    assert len(store.read().list("request")) == before
    assert source_intake.intake_run(store.read(), "m").data["full_read"] == 14


def test_the_routes_offer_the_question_after_a_read_and_answer_it(tmp_path):
    ws, cfg, store = make(tmp_path)
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        # The question is open from the moment a source exists, ahead of its first read: the reaches carry no number
        # yet, since nothing was asked of the service.
        assert [bool(s["full_read_open"]) for s in client.get("/api/watch").json()] == [True, True]
        ahead = client.get("/api/watch/m/full-read").json()
        assert [(o["days"], o["count"], o["unknown"]) for o in ahead["options"]] == [(d, 0, True) for d in (14, 30, 90)]
        assert client.post("/api/watch/m/read").status_code == 200
        assert [bool(s["full_read_open"]) for s in client.get("/api/watch").json()] == [True, True]
        shown = client.get("/api/watch/m/full-read").json()
        assert [o["days"] for o in shown["options"]] == [14, 30, 90] and shown["answered"] is None
        assert not any(o["unknown"] for o in shown["options"])  # counted once the read has landed
        assert client.post("/api/watch/m/full-read", json={"days": 0}).status_code == 200
        assert client.get("/api/watch/m/full-read").json()["answered"] == 0
        # The source that was read is answered; the one never read keeps its own question.
        assert [bool(s["full_read_open"]) for s in client.get("/api/watch").json()] == [False, True]


def test_the_people_step_shows_the_waiting_look_with_its_estimate_and_what_to_send_to_start_it(tmp_path):
    ws, cfg, store = make(tmp_path)
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        live = app.state.store
        refresh(ws, live, cfg, "m", NOW)
        refresh(ws, live, cfg, "m2", NOW)
        request = person_look.queue(live, cfg, NOW)
        run_look(ws, cfg, live, request)
        shown = client.get("/api/setup/people-suggestions").json()
        assert (shown["state"], shown["people"], shown["request"]) == ("waiting", [], request)
        assert shown["estimate_usd"] > 0
        started = client.post(f"/api/requests/{request}/go", json={"read_version": shown["read_version"]})
        assert started.status_code == 200
        assert client.get("/api/setup/people-suggestions").json()["state"] == "working"
