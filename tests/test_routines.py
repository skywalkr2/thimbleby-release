"""Routines the person keeps (S-0530, design 6.22, "Learning the person from their mail and calendar"): a kept routine
is a fact the steward reads. It is never offered as a free slot, no reminder lands in it, and one that is only proposed,
or that the person discarded, changes nothing. Names, ids and times come from the fixtures; the day moves with the
clock each test passes in."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from engine import dated_facts, day_capacity, propose_times, reminder_lines, routines
from engine.records import Routine
from engine.storage import Store, WriteContext
from engine.today import zone
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

# A Monday at 9:00 on the person's clock (UTC here).
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
_TEST = WriteContext(actor="pm", trust="trusted", op="test.routines")
ENV = {
    "COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC",
    "COCKPIT__STEWARD__REMINDERS__WORKING_START": "09:00",
    "COCKPIT__STEWARD__REMINDERS__WORKING_END": "17:30",
    "COCKPIT__STEWARD__REMINDERS__WORKING_FIRST_DAY": "monday",
    "COCKPIT__STEWARD__REMINDERS__WORKING_LAST_DAY": "friday",
}
WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday"]


class Clock:
    def __call__(self) -> str:
        return NOW.isoformat(timespec="seconds")


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env=ENV)
    store = Store(ws.db_path, cfg=cfg, clock=Clock())
    yield ws, cfg, store
    store.close()


def make(store, kind, **data) -> str:
    with store.transaction() as tx:
        return tx.create(kind, data, _TEST).id


def routine(store, cfg, label="Morning swim", days=WEEK, start="09:00", end="10:00", status="active") -> str:
    kept = status == "active"
    return make(
        store,
        "glossary_entry",
        text=f"{label}: {days[0]} {start} to {end}",
        term=label,
        meaning=f"{days[0]} {start} to {end}",
        routine={"days": days, "start": start, "end": end},
        origin="input",
        trust="trusted",
        learned_at=NOW.isoformat(),
        status=status,
        kept_by=cfg.workspace.user.person if kept else None,
        kept_at=NOW.isoformat() if kept else None,
    )


def spans(found, cfg):
    here = zone(cfg)
    return [(s.start.astimezone(here), s.end.astimezone(here)) for s in found]


# ---- what a routine is -----------------------------------------------------------------------------------------------


def test_only_a_kept_routine_is_read_and_it_holds_its_days_and_times(env):
    _, cfg, store = env
    kept = routine(store, cfg, "Morning swim", ["tuesday", "thursday"], "07:00", "08:00")
    routine(store, cfg, "Proposed one", ["monday"], status="proposed")
    routine(store, cfg, "Thrown away", ["monday"], status="discarded")
    (slot,) = routines.kept(store.read())
    assert (slot.entry, slot.label, slot.days, slot.start, slot.end) == (
        kept,
        "Morning swim",
        (1, 3),
        time(7, 0),
        time(8, 0),
    )


def test_a_routine_that_ends_before_it_starts_or_names_a_day_twice_is_refused():
    for bad in (
        {"days": ["monday"], "start": "10:00", "end": "09:00"},
        {"days": ["monday", "monday"], "start": "09:00", "end": "10:00"},
        {"days": [], "start": "09:00", "end": "10:00"},
        {"days": ["someday"], "start": "09:00", "end": "10:00"},
    ):
        with pytest.raises(ValueError):
            Routine.model_validate(bad)


# ---- never offered as a free slot ------------------------------------------------------------------------------------


def test_a_kept_routine_is_not_free_time_in_the_days_capacity_and_a_proposed_one_is(env):
    _, cfg, store = env
    routine(store, cfg, "Lunch walk", ["monday"], "12:00", "13:00", status="proposed")
    assert day_capacity.free_minutes(store, cfg, NOW) == 510  # 09:00 to 17:30
    routine(store, cfg, "Lunch walk", ["monday"], "12:00", "13:00")
    assert day_capacity.free_minutes(store, cfg, NOW) == 450
    routine(store, cfg, "Tuesday only", ["tuesday"], "09:30", "11:30")
    assert day_capacity.free_minutes(store, cfg, NOW) == 450  # another day's routine takes nothing from today


def test_a_kept_routine_is_never_offered_as_a_time_to_propose_and_the_slots_move_to_the_free_time(env):
    _, cfg, store = env
    event = make(
        store,
        "event",
        trust="trusted",
        title="Planning call",
        start="2026-10-26T15:00:00+00:00",
        end="2026-10-26T16:00:00+00:00",
    )
    before = spans(propose_times.slots(store.read(), cfg, NOW, event), cfg)
    assert before and before[0][0].hour == 9  # nothing keeps the first morning hours back yet
    routine(store, cfg, "Morning swim", WEEK, "09:00", "11:00")
    after = spans(propose_times.slots(store.read(), cfg, NOW, event), cfg)
    assert after
    assert all(start.time() >= time(11, 0) or start.time() < time(9, 0) for start, _ in after)
    here = zone(cfg)
    held = routines.busy(routines.kept(store.read()), here, NOW, NOW + timedelta(days=14))
    for start, end in after:
        assert not any(b.start < end and start < b.end for b in held)


def test_a_discarded_routine_blocks_nothing(env):
    _, cfg, store = env
    routine(store, cfg, "Morning swim", WEEK, "09:00", "11:00", status="discarded")
    assert day_capacity.free_minutes(store, cfg, NOW) == 510


# ---- no reminder lands in it -----------------------------------------------------------------------------------------


def test_a_reminder_the_assistant_places_never_lands_inside_a_kept_routine(env):
    _, cfg, store = env
    day = datetime(2026, 12, 15, tzinfo=UTC).date()
    plain = dated_facts.reminder_moment(cfg, day, "renewal", NOW, store.read())
    assert plain == datetime(2026, 12, 1, 9, 0, tzinfo=UTC)  # the morning the working hours start
    routine(store, cfg, "Morning swim", WEEK, "09:00", "10:30")
    placed = dated_facts.reminder_moment(cfg, day, "renewal", NOW, store.read())
    assert placed == datetime(2026, 12, 1, 10, 30, tzinfo=UTC)  # where the routine ends
    assert routines.covering(routines.kept(store.read()), placed, zone(cfg)) is None


def test_a_reminder_that_comes_due_inside_a_kept_routine_reaches_the_person_when_it_ends(env):
    _, cfg, store = env
    action = make(
        store,
        "action",
        text="Send the estimate",
        owners=[{"person": cfg.workspace.user.person}],
        remind_at=NOW.isoformat(),
    )
    assert [d.action for d in reminder_lines.plan(store.read(), cfg, NOW).now] == [action]
    routine(store, cfg, "Morning swim", WEEK, "08:30", "10:00")
    assert reminder_lines.plan(store.read(), cfg, NOW).now == []
    assert reminder_lines.plan(store.read(), cfg, NOW + timedelta(minutes=59)).now == []
    later = reminder_lines.plan(store.read(), cfg, NOW + timedelta(hours=1, minutes=2))
    assert [d.action for d in later.now] == [action]


def test_a_dated_facts_reminder_waits_for_the_end_of_a_kept_routine(env):
    _, cfg, store = env
    fact = make(
        store,
        "fact",
        text="The plan renews",
        on="2026-10-30",
        on_kind="renewal",
        remind_at=NOW.isoformat(),
    )
    assert [f.id for f in dated_facts.coming(store.read(), cfg, NOW)] == [fact]
    routine(store, cfg, "Morning swim", WEEK, "08:30", "10:00")
    assert dated_facts.coming(store.read(), cfg, NOW) == []
    assert [f.id for f in dated_facts.coming(store.read(), cfg, NOW + timedelta(hours=1, minutes=1))] == [fact]


def test_back_to_back_routines_are_cleared_together(env):
    _, cfg, store = env
    routine(store, cfg, "Swim", ["monday"], "09:00", "10:00")
    routine(store, cfg, "Stretch", ["monday"], "10:00", "10:30")
    here = zone(cfg)
    assert routines.clear_of(routines.kept(store.read()), NOW, here) == datetime(2026, 10, 19, 10, 30, tzinfo=UTC)
    free = datetime(2026, 10, 19, 11, 0, tzinfo=UTC)
    assert routines.clear_of(routines.kept(store.read()), free, here) == free
