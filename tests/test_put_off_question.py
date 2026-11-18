"""An answer that puts a question off to a later day holds that question to that day (design 6.8, 6.32; story S-0647).
The person's path: "let's follow up on this in 2 days" on a Tuesday leaves the question open but held until Thursday:
it is gone from Today and the decisions list, listed as put off until Thursday, back on Thursday, and no to-do is added
for the same thing. Words with no readable day change nothing. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from engine import answer_hold, open_items, today_queue
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

_PM = WriteContext("pm", "trusted", "test")
PROJECT = fixture_records(DEMO_B, "project")[0]["id"]
TUESDAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
THURSDAY = date(2026, 11, 19)
LATER = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def ask(store, cfg, **more) -> str:
    fields = {"to": cfg.workspace.user.person, "title": "Which day suits the handover?", "kind": "decision", **more}
    with store.transaction() as tx:
        return tx.create("question", fields, _PM).id


def meeting(store, title, start) -> str:
    with store.transaction() as tx:
        return tx.create(
            "event", {"title": title, "start": start, "end": None, "project": PROJECT, "trust": "trusted"}, _PM
        ).id


def on_today(env, qid, now=NOW) -> bool:
    ws, cfg, store = env
    return any(line.question == qid for line in today_queue.queue(ws, store, cfg, now))


def listed(env, qid, today):
    _, cfg, store = env
    return next(q for q in open_items.open_questions(store, cfg, today) if q.id == qid)


def test_in_2_days_on_a_tuesday_holds_the_question_until_thursday_and_it_comes_back_then(env):
    _, cfg, store = env
    qid = ask(store, cfg)
    assert on_today(env, qid)
    held = answer_hold.hold(store, cfg, qid, "Let's follow up on this in 2 days", today=TUESDAY)
    assert held is not None and held.day == THURSDAY
    data = store.read().get("question", qid).data
    assert data["status"] == "open" and data["held_for"]["on"] == "2026-11-19"  # not closed: the same question waits
    assert not on_today(env, qid)  # off Today
    row = listed(env, qid, TUESDAY)
    assert (row.state, row.held_until, row.yours) == ("later", "2026-11-19", True)  # off the decisions list: put off
    assert row.chases == 0 and row.waiting_days is None  # never chased
    assert on_today(env, qid, LATER)  # back on Thursday
    assert listed(env, qid, THURSDAY).state == "yours"


def test_friday_and_a_meetings_day_are_read_by_the_day_reader(env):
    _, cfg, store = env
    friday = ask(store, cfg)
    assert answer_hold.hold(store, cfg, friday, "Let's follow up on Friday.", today=TUESDAY).day == date(2026, 11, 20)
    thursdays = meeting(store, "Thursday's meeting", "2026-11-19T14:00:00+00:00")
    after = ask(store, cfg)
    held = answer_hold.hold(store, cfg, after, "let's follow up after Thursday's meeting", today=TUESDAY)
    assert held is not None and held.held_for == {"event": thursdays} and held.day == THURSDAY
    moved = ask(store, cfg)
    answer_hold.hold(store, cfg, moved, "follow up after Thursday's meeting", today=TUESDAY)
    with store.transaction() as tx:  # the meeting moves: the question moves with it
        cur = tx.get("event", thursdays)
        tx.update("event", thursdays, {"start": "2026-11-20T14:00:00+00:00"}, _PM, read_version=cur.version)
    assert listed(env, moved, TUESDAY).held_until == "2026-11-20"
    by_day = ask(store, cfg)
    assert answer_hold.hold(store, cfg, by_day, "Let's revisit this after Thursday", today=TUESDAY).day == THURSDAY


@pytest.mark.parametrize(
    "words",
    [
        "Let's follow up on this soon",  # no day to read
        "Friday",  # a day, but not putting anything off: an answer
        "Use the 25th of March cover",  # no word that puts it off
    ],
)
def test_words_with_no_readable_later_day_change_nothing(env, words):
    _, cfg, store = env
    qid = ask(store, cfg)
    assert answer_hold.hold(store, cfg, qid, words, today=TUESDAY) is None
    assert store.read().get("question", qid).data.get("held_for") is None and on_today(env, qid)


def test_only_an_open_question_to_the_person_that_asks_for_a_choice_is_put_off(env):
    _, cfg, store = env
    other = fixture_records(DEMO_B, "person")[-1]["id"]
    assert other != cfg.workspace.user.person
    to_other = ask(store, cfg, to=other)
    assert answer_hold.hold(store, cfg, to_other, "follow up on Friday", today=TUESDAY) is None
    who = ask(store, cfg, resolves={"kind": "owner", "action": "ACT-1"})
    assert answer_hold.hold(store, cfg, who, "follow up on Friday", today=TUESDAY) is None


def test_a_run_about_a_put_off_question_adds_no_todo_for_the_same_thing(env):
    import json

    from engine.ai.adapters.stub import set_responder
    from engine.ai.router import Router
    from engine.dispatcher import process
    from engine.intake import note_as_input
    from engine.lists import ensure as ensure_lists

    ws, cfg, store = env
    ensure_lists(store)
    qid = ask(store, cfg)
    words = "Let's follow up on this in 2 days"
    answer_hold.hold(store, cfg, qid, words, today=TUESDAY)
    request = note_as_input(ws, store, cfg, item=("question", qid), text=words, route="change_requested", now=NOW)
    owner = fixture_records(DEMO_B, "person")[0]["id"]
    op = {"op": "action.add", "text": "Follow up on the handover day", "owners": [owner], "evidence": {"quote": words}}
    before = len(store.read().list("action"))
    set_responder(lambda task: json.dumps({"summary": "Added a to-do.", "ops": [op]}))
    try:
        process(ws, store, cfg, Router(cfg, store, env={}), request, now=NOW)
    finally:
        set_responder(None)
    assert len(store.read().list("action")) == before
    outcomes = [o for c in store.read().list("changeset") for o in c.data["ops"] if o["op"]["op"] == "action.add"]
    assert outcomes and all(o["status"] != "applied" for o in outcomes)
    assert any(p["check"] == "put-off-question" for o in outcomes for p in o.get("problems", []))


def test_the_answer_and_change_routes_hold_the_question_and_hand_nothing_in(tmp_path):
    from fastapi.testclient import TestClient

    from api.app import create_app

    ws = init_workspace(tmp_path / "api", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    app = create_app(ws, cfg, "put-off", ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": "Bearer put-off"}) as client:
        store = app.state.store
        first, second, plain = (ask(store, cfg) for _ in range(3))
        done = client.post(f"/api/questions/{first}/answer", json={"text": "Let's follow up on this in 2 days"})
        assert done.status_code == 200 and done.json()["request"] is None
        said = client.post(f"/api/items/question/{second}/change", json={"note": "follow up on Friday please"})
        assert said.status_code == 200 and said.json()["request"] is None and said.json()["signal"] is None
        for qid in (first, second):
            data = store.read().get("question", qid).data
            assert data["status"] == "open" and data["held_for"]["on"] > date.today().isoformat()
        assert store.read().list("request") == []
        closed = client.post(f"/api/questions/{plain}/answer", json={"text": "Tuesday works"})
        assert closed.status_code == 200 and store.read().get("question", plain).data["status"] == "answered"
        shown = {q["id"]: q for q in client.get("/api/open-items").json()["questions"]}
        assert shown[first]["state"] == "later" and shown[first]["yours"] is True
