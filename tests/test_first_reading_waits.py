"""First reading and People say what they wait for (S-0667, design 6.32 and 7.8): a source the mail service asked to
wait on counts as waiting, with its time, and lets the person go on; what is still being read is named; the look at who
the person deals with is queued when every first read is in, looks again after an older read ends when the tally
changed, and counts an address as asked only while its counts are the same; People says why it is empty. Names and
days come from the fixtures; the AI is the stub."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine import person_look, setup
from engine.storage import WriteContext
from engine.watch import _record, refresh
from tests.test_first_sign_in import NOW, TOKEN, make
from tests.test_setup_reginald import _found

_ENGINE = WriteContext(actor="engine", trust="trusted", op="test")

pytestmark = pytest.mark.usefixtures("first_window_held")


@pytest.fixture
def env(tmp_path):
    ws, cfg, store = make(tmp_path)
    yield ws, cfg, store
    store.close()


def throttle(store, source, at, until):
    _record(store, source, at, time.monotonic(), "throttled", retry_at=until.isoformat(), wait_seconds=600)


def asked(store, addresses_and_counts, state="done"):
    """A look an earlier week made, with the addresses and counts it was shown."""
    with store.transaction() as tx:
        tx.create(
            "request",
            {
                "task": person_look.TASK,
                "origin": "schedule",
                "state": state,
                "asked_about": list(addresses_and_counts),
                "asked_counts": {a: list(c) for a, c in addresses_and_counts.items()},
                "created_at": NOW.isoformat(),
            },
            _ENGINE,
        )


def test_first_reading_names_what_is_still_being_read(env):
    ws, cfg, store = env
    shown = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
    assert (shown.stage, shown.read, shown.sources) == ("fetching", 0, 2)
    assert shown.pending == [s.label for s in cfg.watch.sources]
    refresh(ws, store, cfg, "m", NOW)
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).pending == [cfg.watch.sources[1].label]
    cfg.ui.walkthrough.reading_names = 1  # a longer list than the setting allows is counted, not named
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).pending == [cfg.watch.sources[1].label]
    cfg.ui.walkthrough.reading_names = 1
    refresh(ws, store, cfg, "m2", NOW)
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW + timedelta(minutes=1)).pending == []


def test_a_first_read_the_service_asked_to_wait_on_is_waiting_with_its_time_and_not_stuck(env):
    ws, cfg, store = env
    until = NOW + timedelta(minutes=10)
    refresh(ws, store, cfg, "m", NOW)
    throttle(store, "m2", NOW, until)
    shown = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
    assert (shown.state, shown.stage) == ("working", "waiting")
    assert (shown.read, shown.waiting, shown.sources, shown.pending) == (1, 1, 2, [])
    assert datetime.fromisoformat(shown.until) == until
    assert person_look.queue(store, cfg, NOW) is None  # the look waits for every first read
    # Once the time has come it is read again: no longer waiting, it is being read; then read, and the look is due.
    later = until + timedelta(seconds=1)
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), later).stage == "fetching"
    refresh(ws, store, cfg, "m2", later)
    assert person_look.queue(store, cfg, later) is not None


def test_a_throttled_source_that_was_read_before_is_not_waiting_for_its_first_read(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    throttle(store, "m2", NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW + timedelta(hours=1)).waiting == 0


def test_an_address_is_asked_again_only_when_its_counts_changed(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    now = person_look._counts_of(person_look.tally_lines(store, cfg))
    changed = next(iter(now))
    assert len(now) >= 2
    asked(store, {a: ([c[0] + 5, c[1]] if a == changed else c) for a, c in now.items()})
    shown = [line.split(" | ")[0] for line in person_look.tally_lines(store, cfg)]
    assert shown == [changed]  # every other address is the same as when it was read


def test_an_address_read_with_the_counts_it_has_is_not_asked_about_again(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    asked(store, person_look._counts_of(person_look.tally_lines(store, cfg)))
    assert person_look.tally_lines(store, cfg) == []


def test_a_look_inside_the_week_follows_a_read_that_ended_and_a_changed_tally(env):
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    first = person_look.queue(store, cfg, NOW)
    assert first is not None
    counts = person_look._counts_of(person_look.tally_lines(store, cfg))
    first_address = next(iter(counts))
    with store.transaction() as tx:  # the look was done, having read every address with its counts then
        current = tx.get("request", first)
        tx.update(
            "request",
            first,
            {"state": "done", "asked_counts": {a: [c[0], c[1] + (a == first_address)] for a, c in counts.items()}},
            _ENGINE,
            read_version=current.version,
        )
    later = NOW + timedelta(days=1)
    assert person_look.queue(store, cfg, later) is None  # a day on, no read ended: nothing to look at again
    run = next(r for r in store.read().list("watch_run") if r.data["source"] == "m")
    with store.transaction() as tx:
        tx.update(
            "watch_run",
            run.id,
            {"older_finished_at": (NOW + timedelta(hours=5)).isoformat()},
            _ENGINE,
            read_version=tx.get("watch_run", run.id).version,
        )
    again = person_look.queue(store, cfg, later)
    assert again is not None
    assert store.read().get("request", again).data["asked_about"] == [
        first_address
    ]  # only the one whose counts changed


def test_people_says_what_it_waits_for_and_until_when(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.ai.smoke.ai_state", lambda ws, cfg, store: ("ok", None))
    ws, cfg, store = make(tmp_path)
    store.close()
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        live = app.state.store
        until = datetime.now(UTC) + timedelta(hours=1)
        throttle(live, "m", datetime.now(UTC), until)
        shown = client.get("/api/setup/people-suggestions").json()
        assert (shown["state"], shown["people"]) == ("not_yet", [])
        assert datetime.fromisoformat(shown["until"]) == until
        reading = client.get("/api/setup").json()["reading"]
        assert reading["waiting"] == 1 and datetime.fromisoformat(reading["until"]) == until


def test_a_full_read_keeps_about_how_many_the_choice_showed_so_the_card_can_say_n_of_about_m(env):
    from engine import source_intake

    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    shown = source_intake.full_read_options(ws, store, cfg, "m", NOW)
    source_intake.answer_full_read(ws, store, cfg, "m", shown[1].days, NOW)
    waiting = source_intake.older_read_waiting(store.read(), "m")
    assert waiting["about"] == shown[1].count > 0 and waiting["taken"] == 0


def test_the_end_of_the_header_sweep_lets_the_look_run_again_and_a_sweep_still_going_does_not():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from engine import person_look

    looked = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)

    class View:
        def __init__(self, runs):
            self.runs = [SimpleNamespace(data=d) for d in runs]

        def list(self, kind):
            return self.runs if kind == "watch_run" else []

    going = View([{"header_sweep": {"kind": "reading"}}])
    ended = View([{"header_sweep": None, "header_sweep_finished_at": "2026-11-19T09:30:00+00:00"}])
    before = View([{"header_sweep": None, "header_sweep_finished_at": "2026-11-19T08:30:00+00:00"}])
    assert not person_look.header_sweep_finished_since(going, looked)
    assert person_look.header_sweep_finished_since(ended, looked)
    assert not person_look.header_sweep_finished_since(before, looked)


def test_a_source_the_service_asked_to_wait_on_is_read_again_when_its_time_comes_not_a_whole_interval_later(env):
    from engine.watch import due, interval_minutes

    ws, cfg, store = env
    source = cfg.watch.sources[0]
    throttle(store, source.id, NOW, NOW + timedelta(seconds=5))
    interval = timedelta(minutes=interval_minutes(store, cfg, source))
    assert interval > timedelta(minutes=2)
    assert source.id not in due(store, cfg, NOW + timedelta(seconds=4))  # still inside the service's wait
    assert source.id in due(store, cfg, NOW + timedelta(seconds=6))  # the wait is over, long before the interval


def test_the_background_pass_wakes_when_a_services_wait_runs_out_not_up_to_a_minute_later(env):
    from types import SimpleNamespace

    from engine.watch import next_retry_in
    from engine.worker import Worker

    ws, cfg, store = env
    rest = Worker.JOBS_WAIT_SECONDS

    def wait_at(now):
        return Worker._jobs_wait(SimpleNamespace(store=store, cfg=cfg, now=lambda: now, JOBS_WAIT_SECONDS=rest))

    assert next_retry_in(store, cfg, NOW) is None
    assert wait_at(NOW) == rest  # nothing waits on a service: the plain rest
    source = cfg.watch.sources[0]
    throttle(store, source.id, NOW, NOW + timedelta(seconds=12))
    assert next_retry_in(store, cfg, NOW) == 12
    assert wait_at(NOW) == 12  # wakes when the wait is over, not a whole rest later
    assert wait_at(NOW + timedelta(seconds=30)) == 5  # over already: a short floor, never a busy loop
    throttle(store, source.id, NOW, NOW + timedelta(minutes=10))
    assert wait_at(NOW) == rest  # a long wait never makes the rest longer


def test_first_reading_says_requests_held_for_a_restart_wait(env):
    """H5-18: work held until the person restarts the app is counted on the step, so it never sits on "working"
    without saying why."""
    from engine.worker import RESTART_NEEDED

    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).restart_waits == 0
    with store.transaction() as tx:
        tx.create(
            "request",
            {
                "task": "notes",
                "origin": "input",
                "state": "queued",
                "waiting": RESTART_NEEDED,
                "created_at": NOW.isoformat(),
            },
            _ENGINE,
        )
    shown = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
    assert (shown.state, shown.stage, shown.restart_waits) == ("working", "sorting", 1)


def _queue_sorting(store, estimate, state="queued"):
    with store.transaction() as tx:
        tx.create(
            "request",
            {
                "task": "notes",
                "origin": "input",
                "state": state,
                "range_usd": [estimate, estimate],
                "created_at": NOW.isoformat(),
            },
            _ENGINE,
        )


def _spent(store, usd):
    run = {"task": "notes", "provider": "main", "model": "m", "tier": "routine", "cost_usd": usd, "outcome": "ok"}
    with store.transaction() as tx:
        tx.create("run", {**run, "request": None, "started_at": NOW.isoformat()}, _ENGINE)


def test_first_reading_says_which_spending_limit_holds_its_work_and_when_it_lifts(env):
    """H5-39: queued work the day's limit has no room for never sits on "sorting" without a word: the step is held by
    the limit, with the moment it lifts (the next UTC midnight; the next month's first day for the month's limit)."""
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    cfg.ai.budgets.per_day_usd, cfg.ai.budgets.per_month_usd = 2.0, 30.0
    _queue_sorting(store, 0.01)
    plain = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
    assert (plain.stage, plain.limit, plain.limit_until) == ("sorting", None, None)
    _spent(store, 1.995)  # not used up, but less than the least waiting request is estimated to cost
    held = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
    assert (held.state, held.stage, held.limit) == ("working", "limit", "day")
    midnight = datetime(NOW.year, NOW.month, NOW.day, tzinfo=UTC) + timedelta(days=1)
    assert datetime.fromisoformat(held.limit_until) == midnight
    _spent(store, 1.0)  # used up
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).stage == "limit"
    # A request caught mid-attempt by the worker's own retries doesn't lift the hold.
    _queue_sorting(store, 0.01, state="running")
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).stage == "limit"
    # The month's limit, when it is the nearer, says so and lifts on the first of the next month.
    cfg.ai.budgets.per_month_usd = 2.5
    with store.transaction() as tx:
        for r in tx.list("request"):
            if r.data["state"] == "running":
                tx.update("request", r.id, {"state": "done"}, _ENGINE, read_version=r.version)
    month = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
    assert (month.stage, month.limit) == ("limit", "month")
    nxt = datetime.fromisoformat(month.limit_until)
    assert (nxt.day, nxt.hour) == (1, 0) and (nxt.year, nxt.month) > (NOW.year, NOW.month)


def test_older_mails_queued_work_does_not_hold_first_reading(env):
    """H5-40: only a source's first window is waited for; the older read's queued work carries on in the background."""
    ws, cfg, store = env
    refresh(ws, store, cfg, "m", NOW)
    refresh(ws, store, cfg, "m2", NOW)
    source = cfg.watch.sources[0].id

    def intake(older, state="queued"):
        with store.transaction() as tx:
            tx.create(
                "request",
                {
                    "task": "notes",
                    "origin": "input",
                    "state": state,
                    "intake": source,
                    "intake_older": older,
                    "created_at": NOW.isoformat(),
                },
                _ENGINE,
            )

    for _ in range(3):
        intake(True)
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).stage != "sorting"
    intake(False)
    assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).stage == "sorting"


def test_the_order_of_work_puts_the_look_and_first_windows_before_older_background_work():
    """H5-40: a look queued after 200 older-read requests runs next; background work runs when nothing is ahead."""
    from engine.worker import run_rank

    older = [{"task": "notes", "origin": "input", "intake": "s", "intake_older": True} for _ in range(200)]
    look = {"task": person_look.TASK, "origin": "schedule"}
    window = {"task": "notes", "origin": "input", "intake": "s"}
    mine = {"task": "notes", "origin": "pm"}
    order = sorted([*older, look, window, mine], key=run_rank)
    assert order[:3] == [mine, look, window]
    assert order[3:] == older
    assert sorted(older, key=run_rank) == older  # nothing ahead: background work runs, in the order made
