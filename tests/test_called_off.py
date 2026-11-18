"""A called-off calendar entry is held, not done (design 6.33; stories S-0001, S-0002). The person's path: a meeting
called off, by them or by its calendar, shows held with its line; the to-dos tied to it are held and never overdue;
giving it a new date brings them back with that date in one change that one Undo reverses; dropping it asks about
its to-dos once. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine import called_off, today_queue
from engine.dispatcher import undo_changeset
from engine.storage import Store, StoreError, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

_PM = WriteContext("pm", "trusted", "test")
OWNER = fixture_records(DEMO_B, "person")[0]["id"]
PROJECT = fixture_records(DEMO_B, "project")[0]["id"]
NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def entry(store, title="Walkthrough", start="2026-11-12T14:00:00+00:00", **more) -> str:
    fields = {"title": title, "start": start, "end": None, "project": PROJECT, "trust": "trusted"}
    with store.transaction() as tx:
        return tx.create("event", {**fields, **more}, _PM).id


def todo(store, event, text="Send the agenda", due="2026-11-12", **more) -> str:
    fields = {"text": text, "owners": [{"person": OWNER}], "due": due, "status": "open", "due_event": event}
    with store.transaction() as tx:
        return tx.create("action", {**fields, **more}, _PM).id


def data(store, kind, ident):
    return store.read().get(kind, ident).data


def test_a_meeting_the_person_calls_off_is_held_with_its_tied_todos_and_never_done(env):
    _, cfg, store = env
    meeting = entry(store)
    tied = todo(store, meeting)
    own_hold = todo(store, meeting, text="Book the room", on_hold={"waiting_for": "the venue", "since": "2026-11-01"})
    called_off.call_off(store, cfg, meeting)
    held = data(store, "event", meeting)
    assert held["cancelled"] and not held.get("dropped")
    assert called_off.is_held(held)
    hold = data(store, "action", tied)["on_hold"]
    assert hold["entry"] == meeting and "Walkthrough" in hold["waiting_for"]
    assert data(store, "action", tied)["status"] == "open"  # held, never done
    assert data(store, "action", own_hold)["on_hold"]["waiting_for"] == "the venue"  # a hold of its own stays


def test_a_held_todo_is_not_overdue_and_the_entry_has_one_line_to_set_a_new_date_or_drop_it(env):
    ws, cfg, store = env
    meeting = entry(store, start="2026-11-12T14:00:00+00:00")
    tied = todo(store, meeting, due="2026-11-08")  # already past its day
    assert tied in [a for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "overdue" for a in x.actions]
    called_off.call_off(store, cfg, meeting)
    lines = today_queue.queue(ws, store, cfg, NOW)
    kinds = {line.key: line for line in lines}
    line = kinds[f"called_off:{meeting}"]
    assert line.kind == "called_off" and line.event == meeting and "Walkthrough" in line.text
    assert tied not in [a for x in lines if x.kind in ("overdue", "promise", "nudge") for a in x.actions]


def test_a_new_date_brings_the_todos_back_with_it_in_one_change_and_one_undo(env):
    _, cfg, store = env
    meeting = entry(store)
    tied = todo(store, meeting)
    called_off.call_off(store, cfg, meeting)
    change = called_off.new_date(store, cfg, meeting, "2026-11-19T14:00:00+00:00")
    back = data(store, "event", meeting)
    assert not back["cancelled"] and back["start"].startswith("2026-11-19")
    after = data(store, "action", tied)
    assert after["on_hold"] is None and after["due"] == "2026-11-19"
    undo_changeset(store, change)  # the one change is undone as one
    again = data(store, "event", meeting)
    assert again["cancelled"] and again["start"].startswith("2026-11-12")
    assert data(store, "action", tied)["on_hold"]["entry"] == meeting


def test_dropping_asks_about_the_held_todos_once_and_either_answer_ends_the_question(env):
    ws, cfg, store = env
    meeting = entry(store)
    keep = todo(store, meeting, text="Send the agenda")
    gone = todo(store, meeting, text="Print the slides")
    called_off.call_off(store, cfg, meeting)
    with pytest.raises(StoreError):
        called_off.drop(store, cfg, meeting, "  ")  # a reason is required
    called_off.drop(store, cfg, meeting, "The client withdrew")
    assert data(store, "event", meeting)["dropped"] == "The client withdrew"
    assert not called_off.is_held(data(store, "event", meeting))  # closed, not waiting for a date
    keys = [line.key for line in today_queue.queue(ws, store, cfg, NOW)]
    assert f"called_off:{meeting}" not in keys and f"called_off_todos:{meeting}" in keys
    called_off.keep_todos(store, cfg, meeting)
    kept = data(store, "action", keep)
    assert kept["on_hold"] is None and kept["due"] is None and kept["due_event"] is None and kept["status"] == "open"
    assert f"called_off_todos:{meeting}" not in [line.key for line in today_queue.queue(ws, store, cfg, NOW)]
    assert data(store, "action", gone)["status"] == "open"
    with pytest.raises(StoreError):
        called_off.keep_todos(store, cfg, meeting)  # asked once


def test_dropping_the_todos_with_the_entry_gives_them_the_entrys_reason_and_is_not_done(env):
    _, cfg, store = env
    meeting = entry(store)
    tied = todo(store, meeting)
    called_off.call_off(store, cfg, meeting)
    called_off.drop(store, cfg, meeting, "The client withdrew")
    called_off.drop_todos(store, cfg, meeting)
    found = data(store, "action", tied)
    assert found["status"] == "dropped" and found["dropped_reason"] == "The client withdrew"
    assert called_off.held_todos(store.read(), meeting) == []


def test_the_calendars_own_call_off_holds_the_tied_todos_and_a_restore_releases_them(env):
    _, cfg, store = env
    meeting = entry(store)
    tied = todo(store, meeting)
    with store.transaction() as tx:
        tx.update("event", meeting, {"cancelled": True}, _PM, read_version=tx.get("event", meeting).version)
        called_off.sync(tx, meeting, _PM, cfg)
    assert data(store, "action", tied)["on_hold"]["entry"] == meeting
    with store.transaction() as tx:
        tx.update("event", meeting, {"cancelled": False}, _PM, read_version=tx.get("event", meeting).version)
        called_off.sync(tx, meeting, _PM, cfg)
    assert data(store, "action", tied)["on_hold"] is None


NOTES = "Plan from Tuesday: after Thursday's meeting, send the agenda and chase the figures"


def test_calling_a_meeting_off_holds_the_other_todos_from_the_same_notes_and_none_shows_overdue(env):
    """S-0648: the to-dos of one set of notes were tied only to each other; calling off the step they follow now checks
    the others from the same notes for a tie, so none goes overdue and Today doesn't ask to chase anyone."""
    ws, cfg, store = env
    step = entry(store, title="Thursday's meeting", start="2026-11-12T14:00:00+00:00")
    other = entry(store, title="Printer visit", start="2026-11-12T16:00:00+00:00")
    source = {"source": "SRC-notes"}
    tied = todo(store, step, text="Send the agenda", due="2026-11-08", **source)
    untied = [
        todo(store, None, text=text, due="2026-11-08", due_words=words, **source)
        for text, words in (("Chase the figures", "after Thursday's meeting"), ("Chase the quote", "after the printer"))
    ]
    elsewhere = todo(store, None, text="Pay the invoice", due="2026-11-08", due_words="after Thursday's meeting")
    for ident in (tied, *untied, elsewhere):
        assert ident in [a for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "overdue" for a in x.actions]
    called_off.call_off(store, cfg, step)
    chased, unnamed = untied
    for ident in (tied, chased):
        assert data(store, "action", ident)["due_event"] == step
        assert data(store, "action", ident)["on_hold"]["entry"] == step
    assert not data(store, "action", unnamed).get("on_hold") and not data(store, "action", elsewhere).get("on_hold")
    shown = [a for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "overdue" for a in x.actions]
    assert tied not in shown and chased not in shown and unnamed in shown and elsewhere in shown
    assert other  # the other meeting is untouched
    back = called_off.new_date(store, cfg, step, "2026-11-13T14:00:00+00:00")
    assert (
        back
        and data(store, "action", chased)["on_hold"] is None
        and data(store, "action", chased)["due"] == "2026-11-13"
    )


def test_in_a_list_of_meetings_booked_ones_come_first_and_held_ones_last(env):
    from engine import today

    _, cfg, store = env
    held = entry(store, title="Walkthrough", start="2026-11-09T09:30:00+00:00")
    booked = entry(store, title="Standup", start="2026-11-09T15:00:00+00:00")
    called_off.call_off(store, cfg, held)
    titles = [(a.title, a.held) for a in today.agenda(store, cfg, NOW) if a.snapshot in (held, booked)]
    assert titles == [("Standup", False), ("Walkthrough", True)]
