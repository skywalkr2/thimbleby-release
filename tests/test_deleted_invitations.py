"""A deleted invitation never puts a meeting on the schedule (S-0763; design 6.2, 6.22): mail the person deleted is read
for the schedule and learning only, so an invitation, a cancellation or an answer in it makes and changes no
calendar entry, by rule or by the assistant, decided from the item's own calendar data. A booking, an appointment or a
delivery the mail confirms still reaches the schedule. The deleted source is a calendar file with the deleted role (the
rules read the item's calendar data the same way for any source); names and addresses come from the fixtures."""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest
import yaml

from engine import applier
from engine import evaluate as ev
from engine.ai.adapters import stub
from engine.config import load_config
from engine.connectors import EventDetails, EventPerson
from engine.entry_rules import carries_invitation
from engine.intake import hand_in
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store, WriteContext
from engine.today import agenda
from engine.watch import refresh
from engine.workspace import init_workspace
from tests.conftest import DEMO_A, DEMO_B
from tests.test_plain_calendar_entries import (
    EMPTY,
    NOW,
    _identify,
    calendar,
    vevent,
)

_TEST = WriteContext("pm", "trusted", "test")
CASE = "deleted-invitation-adds-no-calendar-entry"


def _sources(tmp_path):
    files = {"calendar": tmp_path / "work.ics", "deleted": tmp_path / "deleted.ics"}
    sources = [
        {
            "id": sid,
            "connector": "calendar",
            "label": sid,
            "first_run": "baseline",
            **({"role": "deleted"} if sid == "deleted" else {}),
            "settings": {"file": str(path), "days_ahead": 30, "expand_days": 60},
        }
        for sid, path in files.items()
    ]
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": sources}))
    return ws, load_config(ws.config_dir, env={}), files


@pytest.fixture
def env(tmp_path):
    ws, cfg, files = _sources(tmp_path)
    store = Store(ws.db_path, cfg=cfg)
    _identify(store)

    def put(source, text, at=NOW):
        files[source].write_text(text)
        os.utime(files[source], (at.timestamp(), at.timestamp()))
        return refresh(ws, store, cfg, source, at)

    for sid in files:
        put(sid, EMPTY, NOW - timedelta(hours=2))
    yield ws, cfg, store, put
    store.close()
    stub.set_responder(None)


def kept(store, source):
    return store.read().find("event", {"source": source})


def on_schedule(store, cfg):
    return [i.title for i in agenda(store, cfg, NOW, NOW.date() + timedelta(days=10))]


def test_a_deleted_invitation_makes_no_entry_and_leaves_the_day_clear(env):
    ws, cfg, store, put = env
    put("deleted", calendar(vevent("a", "Vendor review", invited=True), method="REQUEST"))
    assert kept(store, "deleted") == []
    assert on_schedule(store, cfg) == []


def test_a_deleted_cancellation_and_a_deleted_answer_make_no_entry_either(env):
    ws, cfg, store, put = env
    put("deleted", calendar(vevent("a", "Vendor review", status="CANCELLED", invited=True), method="CANCEL"))
    put("deleted", calendar(vevent("b", "Design sync", with_me=True), method="REPLY"), NOW + timedelta(hours=1))
    assert kept(store, "deleted") == [] and on_schedule(store, cfg) == []


def test_a_deleted_cancellation_leaves_a_meeting_the_calendar_has_as_the_calendar_has_it(env):
    ws, cfg, store, put = env
    put("calendar", calendar(vevent("a", "Vendor review", invited=True), method="REQUEST"))
    put("deleted", calendar(vevent("a", "Vendor review", status="CANCELLED", invited=True), method="CANCEL"))
    [entry] = kept(store, "calendar")
    assert entry.data["cancelled"] is False
    shown = agenda(store, cfg, NOW, NOW.date() + timedelta(days=10))
    assert [(i.title, i.cancelled, i.also_in) for i in shown] == [("Vendor review", False, [])]


def test_deleted_calendar_data_that_is_no_invitation_still_makes_its_entry(env):
    ws, cfg, store, put = env
    put("deleted", calendar(vevent("a", "Planning reminder")))
    assert [e.data["title"] for e in kept(store, "deleted")] == ["Planning reminder"]


def test_an_invitation_is_decided_from_its_calendar_data_never_its_words():
    plain = EventDetails(start="2030-03-09T15:00:00+00:00", entries=True)
    assert not carries_invitation(plain, set(), set())
    assert not carries_invitation(
        EventDetails(start=plain.start, method="PUBLISH", organizer=EventPerson(address="me@example.com")),
        {"me@example.com"},
        set(),
    )
    for more in (
        {"method": "REQUEST"},
        {"method": "cancel"},
        {"cancelled": True},
        {"attendees": (EventPerson(address="a@example.com", response="declined"),)},
        {"organizer": EventPerson(address="other@example.com")},
    ):
        assert carries_invitation(EventDetails(start=plain.start, **more), {"me@example.com"}, set())
    # the snapshot's own form reads the same way
    assert carries_invitation({"start": plain.start, "method": "REQUEST"}, set(), set())


def test_a_deleted_invitation_handed_in_marks_its_request_and_a_deleted_plain_item_does_not(env):
    ws, cfg, store, put = env
    put(
        "deleted",
        calendar(
            vevent("a", "Vendor review", invited=True, description="Agenda attached"),
            vevent("b", "Planning reminder", day="20300310", description="Bring the proofs"),
        ),
    )
    rows = {}
    for request in store.read().list("request"):
        source = store.read().get("source", request.data["source"])
        rows[source.data["title"]] = request.data
    assert rows["Vendor review"]["source_role"] == "deleted" and rows["Vendor review"]["source_invitation"] is True
    assert rows["Planning reminder"]["source_role"] == "deleted" and not rows["Planning reminder"]["source_invitation"]


def _checked(env, op, *, invitation, actor="assistant"):
    ws, cfg, store, put = env
    request = hand_in(ws, store, note="", pasted="Your order has shipped.", now=NOW).request
    marks = {"source_role": "deleted", **({"source_invitation": True} if invitation else {})}
    with store.transaction(notify=False) as tx:
        current = tx.get("request", request)
        tx.update("request", request, marks, _TEST, read_version=current.version)
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    inputs = applier.Inputs(request, None, "Your order has shipped.", "Your order has shipped.", "untrusted")
    ctx = applier.Context(
        store, cfg, People(store, cfg), ("event.add", "event.set", "event.guests", "series.add"), inputs, actor=actor
    )
    return [p.check for p in applier.check(cs, ctx) if p.severity == "refuse"]


ADD = {
    "op": "event.add",
    "title": "Vendor review",
    "start": "2030-03-14T14:00:00+00:00",
    "evidence": {"quote": "Your order has shipped."},
}


def test_the_checks_refuse_an_entry_from_a_deleted_invitation_and_allow_a_deleted_booking(env):
    assert "from-deleted-mail" in _checked(env, ADD, invitation=True)
    assert "from-deleted-mail" not in _checked(env, ADD, invitation=False)
    assert "from-deleted-mail" not in _checked(env, ADD, invitation=True, actor="pm")


def test_the_checks_refuse_a_change_to_an_entry_from_a_deleted_invitation(env):
    ws, cfg, store, put = env
    with store.transaction() as tx:
        entry = tx.create("event", {"title": "Vendor review", "start": "2030-03-14T14:00:00+00:00"}, _TEST).id
    change = {"op": "event.set", "id": entry, "start": "2030-03-15T14:00:00+00:00", "evidence": ADD["evidence"]}
    assert "from-deleted-mail" in _checked(env, change, invitation=True)


def test_the_checks_refuse_guests_and_a_series_from_a_deleted_invitation(env):
    ws, cfg, store, put = env
    with store.transaction() as tx:
        entry = tx.create("event", {"title": "Vendor review", "start": "2030-03-14T14:00:00+00:00"}, _TEST).id
    guests = {"op": "event.guests", "id": entry, "people": ["Sam"], "evidence": ADD["evidence"]}
    series = {"op": "series.add", "title": "Vendor review", "repeats": "weekly", "evidence": ADD["evidence"]}
    for op in (guests, series):
        assert "from-deleted-mail" in _checked(env, op, invitation=True), op["op"]
        assert "from-deleted-mail" not in _checked(env, op, invitation=False), op["op"]


def test_the_deleted_mail_prompt_says_an_invitation_is_learning_only():
    text = (DEMO_A.parent.parent / "engine" / "prompts" / "notes-deleted.md").read_text()
    assert "invitation" in text and "learning only" in text


def test_the_assistants_entry_from_a_deleted_invitation_is_refused_in_the_golden_case(monkeypatch):
    seen = {}
    real = applier.check

    def spy(cs, ctx):
        problems = real(cs, ctx)
        seen["checks"] = [p.check for p in problems]
        return problems

    monkeypatch.setattr(applier, "check", spy)
    answer = json.dumps(
        {
            "summary": "x",
            "ops": [
                {
                    "op": "event.add",
                    "title": "Vendor review",
                    "start": "2026-10-15T14:00",
                    "evidence": {"quote": "You are invited to the vendor review on Thursday, October 15 at 2:00 PM."},
                }
            ],
        }
    )
    monkeypatch.setattr(
        ev, "set_responder", lambda responder: stub.set_responder(None if responder is None else (lambda task: answer))
    )
    ev.evaluate(DEMO_A, stub=True, runs=1, only=[CASE])
    assert "from-deleted-mail" in seen["checks"]
