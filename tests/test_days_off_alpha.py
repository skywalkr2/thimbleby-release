"""Days off before the alpha (S-0695, S-0696; design 6.32): the week ahead names the week's days off, and nobody is
chased on a day they are away or on a holiday. Names, ids and days come from the fixtures; the date is passed in."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from engine import days_off, promises, week_ahead
from engine import packet as packets
from engine.followups import sections
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, without_first_go

_W = WriteContext("engine", "trusted", "test.days_off_alpha")
# The Monday of Thanksgiving week and the two days off in it.
MONDAY = date(2026, 11, 23)
THANKSGIVING = date(2026, 11, 26)
FRIDAY_AFTER = date(2026, 11, 27)


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    without_first_go(ws.config_dir)
    cfg = ws.config(env={"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 14, 0, tzinfo=UTC)


# ---- S-0695: the week ahead and the brief open with the days off -----------------------------------------------------


def test_thanksgiving_weeks_week_ahead_names_both_days_off_and_the_days_left(env):
    ws, cfg, store = env
    card = week_ahead.card_of(ws, store, cfg, at(MONDAY))
    named = dict(card.days_off)
    assert set(named) == {THANKSGIVING, FRIDAY_AFTER}
    assert "Thanksgiving" in named[THANKSGIVING] and "Thanksgiving" in named[FRIDAY_AFTER]
    assert card.working_days == 2  # Tuesday and Wednesday are what is left after today


def test_a_week_with_only_days_off_still_shows_them(env):
    ws, cfg, store = env
    card = week_ahead.card_of(ws, store, cfg, at(MONDAY))
    assert not card.rows or card.state != "empty" or card.days_off
    assert card.days_off


def test_a_week_with_no_days_off_lists_none(env):
    ws, cfg, store = env
    assert week_ahead.card_of(ws, store, cfg, at(date(2026, 10, 19))).days_off == ()


def test_weekend_holidays_are_not_days_off_of_the_working_week(env):
    _, cfg, store = env
    off, _ = week_ahead.days_off_of(store, cfg, date(2026, 7, 1), date(2026, 7, 7))
    assert all(d.weekday() < 5 for d, _ in off)


def test_the_packet_tells_the_assistant_the_days_off_and_the_prompt_asks_for_them_in_the_sentence(env):
    ws, cfg, store = env
    with store.transaction() as tx:
        tx.create(
            "fact",
            {"text": "The case reply is due", "on": "2026-11-25", "on_kind": "deadline", "basis": "person"},
            _W,
        )
    week_ahead.read_again(store, cfg, at(MONDAY))
    request = store.read().list("request")[-1].id
    text = packets.build(ws, store, cfg, request, MONDAY).task.request
    assert "Days off in the week ahead" in text
    assert "2026-11-26 (Thursday): Thanksgiving" in text and "2026-11-27 (Friday): Day After Thanksgiving" in text
    assert "2 working days are left" in text
    assert "days off" in Path("engine/prompts/week-ahead.md").read_text()


# ---- S-0696: nobody is chased on a day they are off ------------------------------------------------------------------


def _told_action(store, cfg, person: str, told: date, **more) -> str:
    with store.transaction() as tx:
        return tx.create(
            "action",
            {
                "text": "Send the signed form",
                "owners": [{"person": person}],
                "status": "open",
                "told": {person: told.isoformat()},
                **more,
            },
            _W,
        ).id


def _other(cfg, store) -> str:
    return next(p.id for p in store.read().list("person") if p.id != cfg.workspace.user.person)


def _row(store, cfg, today, action_id, person):
    section = next(s for s in sections(store, cfg, today) if s.person == person)
    return section, next(a for a in section.actions if a["id"] == action_id)


def _away(store, person: str, start: date, end: date) -> None:
    with store.transaction() as tx:
        found = tx.get("person", person)
        tx.update(
            "person",
            person,
            {"away": [{"start": start.isoformat(), "end": end.isoformat()}]},
            _W,
            read_version=found.version,
        )


def test_someone_away_two_weeks_is_not_chased_on_day_four_and_shows_out_until(env):
    _, cfg, store = env
    wait = cfg.ui.followups.undated_after_days
    person = _other(cfg, store)
    today = date(2026, 10, 14)  # a Wednesday
    told = today - timedelta(days=wait)
    action = _told_action(store, cfg, person, told)
    section, row = _row(store, cfg, today, action, person)
    assert row["chase_due"] and section.out_until is None  # due, and at work
    _away(store, person, today - timedelta(days=4), today + timedelta(days=9))
    section, row = _row(store, cfg, today, action, person)
    assert not row["chase_due"]
    back = today + timedelta(days=12)  # the away period ends on a Friday: back on the Monday
    assert section.out_until == back.isoformat()
    section, row = _row(store, cfg, back, action, person)
    assert row["chase_due"] and section.out_until is None


def test_a_follow_up_due_on_a_holiday_moves_to_the_next_working_day(env):
    _, cfg, store = env
    wait = cfg.ui.followups.undated_after_days
    person = _other(cfg, store)
    action = _told_action(store, cfg, person, THANKSGIVING - timedelta(days=wait))
    section, row = _row(store, cfg, THANKSGIVING, action, person)
    assert not row["chase_due"]
    assert section.out_until == (FRIDAY_AFTER + timedelta(days=3)).isoformat()  # Friday is off too, then the weekend
    assert _row(store, cfg, date(2026, 11, 30), action, person)[1]["chase_due"]


def test_a_promise_line_is_not_due_while_its_person_is_away(env):
    _, cfg, store = env
    pm = cfg.workspace.user.person
    person = _other(cfg, store)
    today = date(2026, 10, 14)
    with store.transaction() as tx:
        tx.create(
            "action",
            {
                "text": "Deliver the draft",
                "owners": [{"person": person}],
                "status": "open",
                "promised_to": [pm],
                "due": (today - timedelta(days=3)).isoformat(),
            },
            _W,
        )
    pending = promises.pending_endings(store.read())
    assert promises.late(store.read(), cfg, pm, today, pending, lambda _a: None)
    _away(store, person, today - timedelta(days=1), today + timedelta(days=3))  # to the Saturday
    assert not promises.late(store.read(), cfg, pm, today, pending, lambda _a: None)
    assert promises.late(store.read(), cfg, pm, today + timedelta(days=5), pending, lambda _a: None)


def test_back_on_is_none_for_someone_at_work_and_skips_rest_days(env):
    _, cfg, store = env
    person = _other(cfg, store)
    assert days_off.back_on(store.read(), cfg, person, date(2026, 10, 14)) is None
    _away(store, person, date(2026, 10, 15), date(2026, 10, 16))  # Thursday and Friday
    assert days_off.back_on(store.read(), cfg, person, date(2026, 10, 15)) == date(2026, 10, 19)


# ---- S-0712: the daily briefs mention a day off that is near ---------------------------------------------------------


def _line(env, form: str, day: date, hour: int = 9):
    from engine import brief

    ws, cfg, store = env
    now = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
    found = brief.build(ws, store, cfg, now, form)
    return [line for s in found.sections for line in s.lines if line.kind == "days_off"], found


def test_the_morning_brief_names_both_days_off_when_tomorrow_and_the_day_after_are_holidays(env):
    lines, found = _line(env, "morning", date(2026, 11, 25))
    assert len(lines) == 1
    assert lines[0].subjects == [THANKSGIVING.isoformat(), FRIDAY_AFTER.isoformat()]
    assert lines[0].state == "tomorrow"
    assert found.sections[0].key == "today" and found.sections[0].lines[0] is lines[0]


def test_the_morning_brief_names_a_day_off_in_the_second_working_day_with_its_reason(env):
    lines, _ = _line(env, "morning", date(2026, 11, 24))
    assert [(line.subjects, line.state) for line in lines] == [([THANKSGIVING.isoformat()], "later")]
    assert "Thanksgiving" in (lines[0].text or "")


def test_the_morning_brief_says_nothing_when_no_day_off_is_that_near(env):
    assert _line(env, "morning", MONDAY)[0] == []
    assert _line(env, "morning", date(2026, 10, 19))[0] == []


def test_the_evening_brief_names_a_day_off_only_the_day_before_it(env):
    lines, found = _line(env, "evening", date(2026, 11, 25), 18)
    assert [(line.subjects, line.state) for line in lines] == [([THANKSGIVING.isoformat()], "tomorrow")]
    assert not found.quiet
    assert _line(env, "evening", date(2026, 11, 24), 18)[0] == []
    assert _line(env, "evening", date(2026, 10, 19), 18)[0] == []


def test_the_monday_briefing_has_no_days_off_line_of_its_own(env):
    lines, found = _line(env, "monday", MONDAY)
    assert lines == [] and found.sections == []
