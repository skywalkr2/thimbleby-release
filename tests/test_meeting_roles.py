"""Meetings the person adds, prepared like calendar entries (design 6.32; stories S-0103, S-0102). A meeting added by
hand that repeats or has a role needs no calendar: each date is prepared on its own from the working day before, one
the person runs gets an outline for the notes after it, one they attend gets what to raise, ask and listen for, a
stand-up marked brief-only has no prep line and no prep page and is a line in the brief, and a prep the person already
has on the entry means no prep line. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine import add_meeting, brief, meeting_prep
from engine.applier import apply_as_person
from engine.schedule import schedule
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

_PM = WriteContext("pm", "trusted", "test")
#: A Friday morning; the next dates of a Monday meeting are the 16th, the 23rd and the 30th.
FRIDAY = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
#: What the store's clock says: records are made on this day.
CLOCK = ["2026-11-09T10:00:00+00:00"]


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"})
    store = Store(ws.db_path, cfg=cfg, clock=lambda: CLOCK[0])
    yield ws, cfg, store
    store.close()


def meeting(env, title="Print sync", day="2026-11-16", **more):
    _, cfg, store = env
    return add_meeting.add_meeting(store, cfg, title, day, "09:00", **more).entry


def lines(env, now):
    _, cfg, store = env
    return meeting_prep.prep_lines(store, cfg, now)


def test_a_repeating_meeting_with_nobody_else_is_prepared_from_the_working_day_before_each_date_on_its_own(env):
    found = meeting(env, repeat="week", role="attend")
    assert lines(env, datetime(2026, 11, 12, 23, 0, tzinfo=UTC)) == []  # Thursday night: not yet
    (friday,) = lines(env, FRIDAY)  # the working day before a Monday is the Friday
    assert friday.event == found and friday.others == 0 and friday.occurrence == "2026-11-16T09:00:00+00:00"
    assert friday.start.isoformat().startswith("2026-11-16T09:00")
    assert lines(env, datetime(2026, 11, 16, 9, 30, tzinfo=UTC)) == []  # it goes when the date starts
    (next_friday,) = lines(env, FRIDAY + timedelta(days=7))
    assert next_friday.occurrence == "2026-11-23T09:00:00+00:00"  # the next date has a line of its own


def test_a_meeting_the_person_added_with_no_repeat_and_no_role_has_no_line_when_nobody_else_is_on_it(env):
    meeting(env)
    assert lines(env, FRIDAY) == []


def test_a_solo_entry_that_repeats_but_has_no_role_gets_no_prepare_line_and_attend_is_stored_as_a_role(env):
    _, cfg, store = env
    yoga = meeting(env, "Yoga class", repeat="week")
    assert lines(env, FRIDAY) == []
    assert store.read().get("event", yoga).data.get("role") is None
    attended = meeting(env, "Print sync", repeat="week", role="attend")
    assert store.read().get("event", attended).data["role"] == "attend"
    assert [line.event for line in lines(env, FRIDAY)] == [attended]


def test_a_meeting_the_person_runs_gets_the_outline_for_notes_after_it(env):
    _, cfg, store = env
    found = meeting(env, repeat="week", role="run")
    shown = meeting_prep.prep(store, cfg, found, FRIDAY)
    assert shown.role == "run" and [g.key for g in shown.guide] == ["decisions", "actions", "questions"]
    assert all(g.items == [] for g in shown.guide)


def test_a_meeting_the_person_attends_gets_what_to_raise_ask_and_listen_for(env):
    _, cfg, store = env
    found = meeting(env, repeat="week", role="attend")
    shown = meeting_prep.prep(store, cfg, found, FRIDAY)
    assert shown.role == "attend" and [g.key for g in shown.guide] == ["raise", "ask", "listen"]


def test_each_date_leads_with_what_changed_on_the_meeting_since_the_date_before_it(env):
    _, cfg, store = env
    found = meeting(env, repeat="week", role="attend")
    mine = [{"person": cfg.workspace.user.person}]
    CLOCK[0] = "2026-11-10T10:00:00+00:00"  # before the first date
    with store.transaction() as tx:
        tx.create("action", {"text": "Order the proofs", "owners": mine, "event": found}, _PM)
    CLOCK[0] = "2026-11-18T10:00:00+00:00"  # between the first date and the second
    with store.transaction() as tx:
        new = tx.create("action", {"text": "Confirm the venue", "owners": mine, "event": found}, _PM).id
    second = meeting_prep.prep(
        store, cfg, found, datetime(2026, 11, 20, 10, 0, tzinfo=UTC), "2026-11-23T09:00:00+00:00"
    )
    assert second.occurrence == "2026-11-23T09:00:00+00:00" and second.start.startswith("2026-11-23T09:00")
    assert [i.id for i in second.since_last] == [new]  # only what came after the first date
    first = meeting_prep.prep(store, cfg, found, FRIDAY, "2026-11-16T09:00:00+00:00")
    assert first.since_last == []  # nothing before the first date


def test_a_brief_only_meeting_has_no_prep_line_and_is_a_line_in_the_brief_that_day(env):
    ws, cfg, store = env
    found = meeting(env, "Daily standup", "2026-11-16", repeat="day", role="brief_only")
    assert lines(env, FRIDAY) == [] and lines(env, datetime(2026, 11, 15, 12, 0, tzinfo=UTC)) == []
    monday = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    day = brief._Day(ws, store, cfg, monday)
    (line,) = brief._standups(day)
    assert (line.kind, line.text, line.at, line.link) == ("standup", "Daily standup", "09:00", None)
    assert line.key.startswith(f"standup:{found}:2026-11-16")
    assert brief._standups(brief._Day(ws, store, cfg, datetime(2026, 11, 14, 7, 0, tzinfo=UTC))) == []  # Saturday


def test_the_schedule_shows_a_brief_only_repeat_two_weeks_ahead_only(env):
    _, cfg, store = env
    meeting(env, "Daily standup", "2026-11-16", repeat="day", role="brief_only")
    assert cfg.steward.meetings.standup_days_ahead == 14
    shown = schedule(store, cfg, datetime(2026, 11, 16, 7, 0, tzinfo=UTC), days=40)
    days = [d.date for d in shown if any(e.item.title == "Daily standup" for e in d.timed)]
    assert days and max(days) == datetime(2026, 11, 16).date() + timedelta(days=14)


def test_a_prep_the_person_made_by_hand_means_no_prep_line_for_it(env):
    _, cfg, store = env
    found = meeting(env, repeat="week", role="attend")
    assert len(lines(env, FRIDAY)) == 1
    apply_as_person(
        store,
        cfg,
        [{"op": "text.edit", "record": {"kind": "event", "id": found}, "field": "prep", "text": "Raise the budget."}],
        "Wrote a prep",
    )
    assert meeting_prep.has_own_prep(store.read(), found)
    assert lines(env, FRIDAY) == []


def test_a_called_off_or_dropped_meeting_is_not_prepared(env):
    from engine import called_off

    _, cfg, store = env
    found = meeting(env, repeat="week", role="attend")
    called_off.call_off(store, cfg, found)
    assert lines(env, FRIDAY) == []


def test_a_meeting_with_nothing_on_its_agenda_says_so_on_its_line_and_page(env):
    _, cfg, store = env
    found = meeting(env, repeat="week", role="attend")
    (line,) = lines(env, FRIDAY)
    assert line.no_agenda and meeting_prep.prep(store, cfg, found, FRIDAY).no_agenda
