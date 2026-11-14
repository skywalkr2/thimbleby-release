"""A meeting the person runs with no agenda by its prep's opening, or that needs someone who is away that day, becomes
one question to the person, once for each date of the meeting (design 6.32; story S-0272). A meeting the person only
attends gets none. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine import add_meeting, meeting_asks
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

_SETUP = WriteContext("pm", "trusted", "test")
#: A Friday morning: the working day before the Monday meeting, when its prep opens.
FRIDAY = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
MONDAY = "2026-11-16"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"})
    store = Store(ws.db_path, cfg=cfg, clock=lambda: "2026-11-09T10:00:00+00:00")
    yield ws, cfg, store
    store.close()


def meeting(env, **more):
    _, cfg, store = env
    return add_meeting.add_meeting(store, cfg, "Print sync", MONDAY, "09:00", **more).entry


def edit(store, kind, record_id, **fields):
    with store.transaction() as tx:
        found = tx.get(kind, record_id)
        tx.update(kind, record_id, fields, _SETUP, read_version=found.version)


def put_on_agenda(store, entry):
    with store.transaction() as tx:
        action = tx.create("action", {"text": "Budget", "owners": [{"person": someone()}]}, _SETUP).id
    item = {"action": action, "added_by": None, "added_at": "2026-11-09T10:00:00+00:00", "text": "Budget"}
    edit(store, "event", entry, agenda=[item])


def asked(store):
    return [q for q in store.read().list("question") if (q.data.get("resolves") or {}).get("kind") == "meeting_ready"]


def someone():
    people = {p["id"]: p for p in fixture_records(DEMO_B, "person")}
    me = fixture_records(DEMO_B, "person")[0]["id"]
    return next(m for t in fixture_records(DEMO_B, "team") for m in t["members"] if m != me and m in people)


def test_a_meeting_the_person_runs_with_no_agenda_is_one_question_to_the_person_asked_once_for_its_date(env):
    _, cfg, store = env
    found = meeting(env, repeat="week", role="run")
    assert meeting_asks.ask(store, cfg, FRIDAY - timedelta(days=1)) == []  # before its prep opens
    (made,) = meeting_asks.ask(store, cfg, FRIDAY)
    (q,) = asked(store)
    assert q.id == made and q.data["to"] == cfg.workspace.user.person and q.data["status"] == "open"
    assert q.data["event"] == found and q.data["resolves"]["date"] == "2026-11-16T09:00:00+00:00"
    assert "Print sync" in q.data["title"] and q.data["matters_for"]
    assert meeting_asks.ask(store, cfg, FRIDAY + timedelta(hours=1)) == []  # the same date is asked once
    edit(store, "question", q.id, status="answered", answer="Budget")
    assert meeting_asks.ask(store, cfg, FRIDAY + timedelta(hours=2)) == []  # whatever state it is in
    (next_one,) = meeting_asks.ask(store, cfg, FRIDAY + timedelta(days=7))  # the next date is its own meeting
    assert asked(store)[-1].id == next_one


def test_a_meeting_the_person_only_attends_or_one_with_an_agenda_and_nobody_away_gets_no_question(env):
    _, cfg, store = env
    meeting(env, repeat="week", role="attend")
    assert meeting_asks.ask(store, cfg, FRIDAY) == []
    ran = meeting(env, repeat="week", role="run")
    put_on_agenda(store, ran)
    assert meeting_asks.ask(store, cfg, FRIDAY) == []


def test_someone_the_meeting_needs_being_away_that_day_is_the_same_one_question_with_the_reason(env):
    _, cfg, store = env
    who = someone()
    ran = meeting(env, repeat="week", role="run")
    put_on_agenda(store, ran)
    edit(store, "event", ran, people=[who])
    edit(store, "person", who, away=[{"start": MONDAY, "label": "vacation"}])
    (made,) = meeting_asks.ask(store, cfg, FRIDAY)
    (q,) = asked(store)
    assert q.id == made and "vacation" in q.data["text"]
    assert meeting_asks.ask(store, cfg, FRIDAY) == []


def test_a_meeting_with_no_agenda_and_someone_away_is_one_question_not_two(env):
    _, cfg, store = env
    who = someone()
    ran = meeting(env, repeat="week", role="run")
    edit(store, "event", ran, people=[who])
    edit(store, "person", who, away=[{"start": MONDAY, "label": "vacation"}])
    assert len(meeting_asks.ask(store, cfg, FRIDAY)) == 1
    (q,) = asked(store)
    assert "agenda" in q.data["text"] and "vacation" in q.data["text"]


def test_a_called_off_meeting_and_one_with_no_prep_line_get_no_question(env):
    _, cfg, store = env
    ran = meeting(env, repeat="week", role="run")
    edit(store, "event", ran, cancelled=True)
    assert meeting_asks.ask(store, cfg, FRIDAY) == []


def test_the_worker_asks_once_and_tells_the_screens_when_it_did(env):
    from engine.worker import Worker

    ws, cfg, store = env
    meeting(env, repeat="week", role="run")
    told = []

    class Events:
        def changed(self):
            told.append(1)

    worker = Worker(ws, store, cfg, Events(), now=lambda: FRIDAY)
    assert len(worker.ask_about_meetings()) == 1 and told == [1]
    assert worker.ask_about_meetings() == [] and told == [1]


def test_the_questions_words_come_from_the_wording_sheet_so_the_workspace_can_change_them(env):
    _, cfg, store = env
    meeting(env, repeat="week", role="run")
    cfg.ui.wording["meeting_ask.no_agenda"] = "No agenda is set."
    cfg.ui.wording["meeting_ask.title"] = "Plan {title} on {day}?"
    (made,) = meeting_asks.ask(store, cfg, FRIDAY)
    question = store.read().get("question", made).data
    assert question["text"] == "No agenda is set." and question["title"].startswith("Plan Print sync on ")
