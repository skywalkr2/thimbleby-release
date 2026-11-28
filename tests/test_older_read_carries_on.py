"""A read of older mail the service slows down keeps what it took and carries on by itself (S-0640): the pages already
read are taken in and held for the go like a finished read's, the date it looked back to moves only over the days read
whole, where it stopped is kept with the source's first read, and the worker carries on from there when the time has
come (throttled: at the service's retry time, or after the setting when it gave none; a failure or no network: after
the setting's wait, up to its number of tries, then Today offers to read the rest). A sign-in problem is not carried
on. Time is passed in, never waited for. Names and days come from the fixtures; the AI is the stub."""

from __future__ import annotations

import warnings
from datetime import UTC, date, datetime, timedelta

import pytest

from engine import connectors, setup, source_intake
from engine.connectors import ConnectorError, MessageDetails, OlderMail, SourceItem
from engine.today_queue import queue
from engine.watch import refresh
from tests.test_source_intake import mail
from tests.test_source_intake import make as make_core

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
# twelve older messages, half a day apart, none inside the first read's window
DAYS = tuple(8 + n / 2 for n in range(12))


class Service:
    """A mail service that answers the newest `size` messages of a range, and refuses the calls the script names."""

    def __init__(self, script: dict[int, ConnectorError], now: datetime = NOW):
        self.script = script
        self.now = now
        self.calls = 0
        self.asked: list[tuple[date, date, int]] = []

    def items(self):
        return [mail(f"o{d}", d, now=self.now) for d in DAYS]

    def count(self, settings, since, before, limit, context):
        return min(limit, len(self.within(since, before)))

    def within(self, since, before):
        found = [m for m in self.items() if since <= date.fromisoformat(m["message"]["received"][:10]) < before]
        return sorted(found, key=lambda m: m["message"]["received"], reverse=True)

    def read(self, settings, since, before, size, context):
        self.calls += 1
        self.asked.append((since, before, size))
        if self.calls in self.script:
            raise self.script[self.calls]
        return [
            SourceItem(**{k: v for k, v in m.items() if k != "message"}, message=MessageDetails(**m["message"]))
            for m in self.within(since, before)[:size]
        ]


def world(tmp_path, monkeypatch, script, page=3):
    service = Service(script)
    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(service.count, service.read))
    ws, cfg, store = make_core(tmp_path, [mail(f"m{d}", d) for d in (1, 2, 3)], settings_extra={"capped": False})
    cfg.watch.look_back_max_items = cfg.watch.full_read_page_items = page
    cfg.watch.full_read_max_items = 100
    cfg.ai.budgets.first_go = False
    refresh(ws, store, cfg, "m", NOW)
    return ws, cfg, store, service


def older_keys(store):
    return {s.data["key"] for s in store.read().find("snapshot", {"source": "m"}) if s.data["key"].startswith("o")}


def handed_in(store):
    view = store.read()
    return {
        (view.get("source", r.data["source"]).data.get("watched") or {}).get("key")
        for r in view.list("request")
        if r.data.get("intake") == "m"
    } - {None}


def test_a_read_the_service_slows_down_keeps_every_message_it_took_and_carries_on_from_where_it_stopped(
    tmp_path, monkeypatch
):
    ws, cfg, store, service = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=90)})
    try:
        first_look = source_intake.back_to_of(store.read(), "m")
        stopped = source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        # What the first page gave is kept: taken in, held for the go like a finished read's.
        assert stopped is not None and stopped.stopped == "throttled" and stopped.taken == 3
        assert len(older_keys(store)) == 3 and handed_in(store) >= older_keys(store)
        # The date moved only over the days read whole, and where the read stopped is kept with the first read.
        reached = source_intake.back_to_of(store.read(), "m")
        assert reached < first_look and reached > (NOW - timedelta(days=14)).date()
        run = source_intake.intake_run(store.read(), "m")
        waiting = run.data["older_read"]
        assert waiting["kind"] == "throttled" and waiting["reach"] == 14 and waiting["before"] == reached.isoformat()
        assert datetime.fromisoformat(waiting["at"]) == NOW + timedelta(seconds=90) and not waiting["gave_up"]
        assert run.data["full_read"] == 14, "the choice is recorded once the read started"
        assert stopped.continues_at == waiting["at"] and not stopped.gave_up
        # Not before the time the service asked for.
        assert source_intake.continue_older_read(ws, store, cfg, "m", NOW + timedelta(seconds=89)) is None
        assert len(older_keys(store)) == 3
        # At that time it carries on from where it stopped, until it finishes.
        done = source_intake.continue_older_read(ws, store, cfg, "m", NOW + timedelta(seconds=90))
        assert done is not None and done.stopped is None
        assert service.asked[1][1] == reached, "the next page starts where the last whole day ended"
        assert older_keys(store) == {f"o{d}" for d in DAYS}, "every message of the reach was read, none twice"
        run = source_intake.intake_run(store.read(), "m")
        assert not run.data.get("older_read"), "nothing waits once it finished"
        assert source_intake.back_to_of(store.read(), "m") == (NOW - timedelta(days=14)).date()
        assert handed_in(store) >= older_keys(store)
        assert source_intake.continue_older_read(ws, store, cfg, "m", NOW + timedelta(hours=1)) is None
    finally:
        store.close()


def test_a_throttled_read_with_no_retry_time_carries_on_after_the_setting(tmp_path, monkeypatch):
    ws, cfg, store, _ = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429")})
    try:
        cfg.watch.older_read_throttle_minutes = 7
        stopped = source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert datetime.fromisoformat(stopped.continues_at) == NOW + timedelta(minutes=7)
    finally:
        store.close()


def test_a_service_that_keeps_failing_without_giving_more_is_not_asked_without_end(tmp_path, monkeypatch):
    outage = ConnectorError("outage", "HTTP 503")
    ws, cfg, store, service = world(tmp_path, monkeypatch, {n: outage for n in range(2, 50)})
    try:
        cfg.watch.older_read_tries = 2
        at = NOW
        done = source_intake.read_full_now(ws, store, cfg, "m", 14, at)
        for _ in range(2):
            assert done.continues_at and not done.gave_up
            at = datetime.fromisoformat(done.continues_at)
            done = source_intake.continue_older_read(ws, store, cfg, "m", at)
        assert done.gave_up and done.continues_at is None
        calls = service.calls
        assert source_intake.continue_older_read(ws, store, cfg, "m", at + timedelta(days=1)) is None
        assert service.calls == calls
    finally:
        store.close()


def test_the_worker_carries_a_stopped_read_on_when_its_time_has_come_and_not_before(tmp_path, monkeypatch):
    from engine.worker import Events, Worker

    ws, cfg, store, _ = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=60)})
    try:
        source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        kept = len(older_keys(store))
        assert source_intake.older_read_due(store.read(), cfg, NOW + timedelta(seconds=59)) == []
        assert source_intake.older_read_due(store.read(), cfg, NOW + timedelta(seconds=60)) == ["m"]
        clock = [NOW + timedelta(seconds=30)]
        worker = Worker(ws, store, cfg, Events(), router_factory=lambda: None, now=lambda: clock[0])
        worker.run_due_watches()
        assert len(older_keys(store)) == kept, "too early"
        clock[0] = NOW + timedelta(seconds=61)
        worker.run_due_watches()
        assert len(older_keys(store)) > kept, "one slice at its time"
        for _ in range(10):  # the rest is read a slice (a page) at a time
            worker.run_due_watches()
        assert not source_intake.intake_run(store.read(), "m").data.get("older_read")
        assert older_keys(store) == {f"o{d}" for d in DAYS}
    finally:
        store.close()


def test_a_failure_carries_on_after_the_wait_up_to_the_tries_then_today_offers_the_rest_and_its_button_carries_on(
    tmp_path, monkeypatch
):
    outage = ConnectorError("outage", "HTTP 503 upstream reset")
    ws, cfg, store, service = world(tmp_path, monkeypatch, {2: outage, 3: outage, 4: outage, 5: outage})
    try:
        cfg.watch.older_read_retry_minutes = 5
        cfg.watch.older_read_tries = 3
        stopped = source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert stopped.stopped == "outage" and datetime.fromisoformat(stopped.continues_at) == NOW + timedelta(
            minutes=5
        )
        at = NOW
        for _ in range(3):  # three tries, none of them getting further
            at += timedelta(minutes=5)
            assert [x for x in queue(ws, store, cfg, at) if x.kind == "older_read"] == []
            source_intake.continue_older_read(ws, store, cfg, "m", at)
        waiting = source_intake.older_read_waiting(store.read(), "m")
        assert waiting["gave_up"] and waiting["at"] is None
        assert source_intake.older_read_due(store.read(), cfg, at + timedelta(days=1)) == []
        (line,) = [x for x in queue(ws, store, cfg, at) if x.kind == "older_read"]
        assert line.source == "m" and line.subject == "Inbox" and line.count == 3 and line.problem_kind == "outage"
        # The button carries on at once, from where it stopped; the service has recovered.
        done = source_intake.continue_older_read(ws, store, cfg, "m", at, force=True)
        assert done is not None and done.stopped is None
        assert not source_intake.intake_run(store.read(), "m").data.get("older_read")
        assert [x for x in queue(ws, store, cfg, at) if x.kind == "older_read"] == []
        assert older_keys(store) == {f"o{d}" for d in DAYS}
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["auth", "no_access"])
def test_a_sign_in_problem_keeps_what_was_read_and_is_not_carried_on(tmp_path, monkeypatch, kind):
    ws, cfg, store, _ = world(tmp_path, monkeypatch, {2: ConnectorError(kind, "HTTP 401")})
    try:
        stopped = source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert stopped.stopped == kind and stopped.continues_at is None and stopped.taken == 3
        assert source_intake.older_read_waiting(store.read(), "m") is None
        assert [x for x in queue(ws, store, cfg, NOW) if x.kind == "older_read"] == []
        assert len(older_keys(store)) == 3
    finally:
        store.close()


def test_a_failure_on_the_very_first_page_that_needs_the_person_keeps_the_plain_words_and_the_question_open(
    tmp_path, monkeypatch
):
    from engine.sides import words_sheet
    from engine.storage import StoreError

    ws, cfg, store, _ = world(tmp_path, monkeypatch, {1: ConnectorError("auth", "the sign-in was withdrawn")})
    try:
        with pytest.raises(StoreError) as raised:
            source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        assert str(raised.value) == words_sheet()["full_read.failed.auth"]
        run = source_intake.intake_run(store.read(), "m")
        assert run.data.get("full_read") is None and not run.data.get("older_read")
        assert older_keys(store) == set()
    finally:
        store.close()


def test_setups_reading_step_counts_what_was_taken_in_after_a_stopped_full_read(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "reads", lambda connector, said=None: ["mail"])  # the fake connector reads mail
    ws, cfg, store, _ = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=60)})
    try:
        first = len(handed_in(store))
        assert _reading(ws, cfg, store).found == first == 3
        source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        stopped = _reading(ws, cfg, store)
        # Only what was really taken in: the first read's three and the first page of the full read, never the pages
        # the service refused.
        assert stopped.found == first + 3 == len(handed_in(store))
        source_intake.continue_older_read(ws, store, cfg, "m", NOW + timedelta(minutes=2))
        assert _reading(ws, cfg, store).found == first + len(DAYS) == len(handed_in(store))
    finally:
        store.close()


def _reading(ws, cfg, store):
    found = [
        setup.Step(id="mail", done=True, skipped=False, counted=True),
        setup.Step(id="ai", done=True, skipped=False, counted=True),
    ]
    return setup.reading(ws, cfg, store, found, NOW)


def test_the_routes_show_where_a_read_stopped_and_the_button_on_today_carries_it_on(tmp_path, monkeypatch):
    import yaml
    from fastapi.testclient import TestClient

    from api.app import create_app

    now = datetime.now(UTC)
    service = Service({2: ConnectorError("outage", "HTTP 503")}, now)
    monkeypatch.setitem(connectors._OLDER, "fake", OlderMail(service.count, service.read))
    ws, cfg, store = make_core(
        tmp_path, [mail(f"m{d}", d, now=now) for d in (1, 2, 3)], settings_extra={"capped": False}
    )
    store.close()
    path = ws.config_dir / "watch.yaml"
    watching = yaml.safe_load(path.read_text())
    watching.update(look_back_max_items=3, full_read_page_items=3, full_read_max_items=100, older_read_tries=1)
    path.write_text(yaml.safe_dump(watching))
    app = create_app(ws, ws.config(env={}), "t", ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        assert client.post("/api/watch/m/read").status_code == 200
        calls = service.calls
        answered = client.post("/api/watch/m/full-read", json={"days": 14}).json()
        assert answered["stopped"] == "queued" and answered["taken"] == 0 and service.calls == calls, "answered at once"
        row = client.get("/api/watch").json()[0]
        assert row["older_read"]["kind"] == "queued" and row["older_read"]["taken"] == 0
        assert row["full_read_open"] is None, "the question is not asked again"
        # The worker's lane reads a slice at a time: the first page is taken in, the second fails.
        config, live = ws.config(env={}), app.state.store
        from engine import reading_lane

        at = datetime.now(UTC) + timedelta(seconds=1)
        reading_lane.run_slices(ws, live, config, at)
        reading_lane.run_slices(ws, live, config, at)
        row = client.get("/api/watch").json()[0]
        assert row["older_read"]["kind"] == "outage" and row["older_read"]["taken"] == 3
        # The carry-on at its time fails again; with one try allowed it gives up and Today offers the rest.
        service.script[3] = ConnectorError("outage", "HTTP 503")
        later = datetime.fromisoformat(row["older_read"]["at"]) + timedelta(seconds=1)
        reading_lane.run_slices(ws, live, config, later)
        (line,) = [x for x in client.get("/api/today/queue").json() if x["kind"] == "older_read"]
        assert line["source"] == "m" and line["subject"] == "Inbox" and line["count"] == 3
        service.script.clear()
        # The button asks the worker to carry on at once and returns at once.
        calls = service.calls
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            done = client.post("/api/watch/m/older-read/continue")
        assert done.status_code == 200 and done.json()["stopped"] == "queued" and service.calls == calls
        datetime.fromisoformat(done.json()["continues_at"])
        assert [w for w in caught if "continues_at" in str(w.message)] == []
        for _ in range(10):
            reading_lane.run_slices(ws, live, config, later)
        assert client.get("/api/watch").json()[0]["older_read"] is None
        assert [x for x in client.get("/api/today/queue").json() if x["kind"] == "older_read"] == []


def test_an_authorized_read_wider_than_fourteen_days_is_not_paused(tmp_path, monkeypatch):
    from engine.config.schema import MAIL_IMPORT_MAX_DAYS

    ws, cfg, store, service = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=90)})
    try:
        source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        run = source_intake.intake_run(store.read(), "m")
        with store.transaction() as tx:
            current = tx.get("watch_run", run.id)
            kept = dict(current.data["older_read"])
            wide = (date.fromisoformat(kept["before"]) - timedelta(days=MAIL_IMPORT_MAX_DAYS + 60)).isoformat()
            kept["since"] = wide
            tx.update("watch_run", run.id, {"older_read": kept}, source_intake._MOVED, read_version=current.version)
        assert source_intake.pause_long_reads(store, cfg, NOW) == []
        waiting = source_intake.older_read_waiting(store.read(), "m")
        assert waiting.get("paused") is None and waiting["since"] == wide and not waiting["gave_up"]
        assert waiting["at"] and source_intake.older_read_due(store.read(), cfg, NOW + timedelta(days=1)) == ["m"]
    finally:
        pass


def test_an_unfinished_onboarding_import_stays_inside_the_cap_and_keeps_what_it_took(tmp_path, monkeypatch):
    from engine.config.schema import MAIL_IMPORT_MAX_DAYS, MAIL_IMPORT_MAX_ITEMS

    ws, cfg, store, service = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=90)})
    try:
        source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
        run = source_intake.intake_run(store.read(), "m")
        with store.transaction() as tx:
            current = tx.get("watch_run", run.id)
            kept = dict(current.data["older_read"])
            kept["onboarding"] = True
            kept["since"] = (date.fromisoformat(kept["before"]) - timedelta(days=MAIL_IMPORT_MAX_DAYS + 60)).isoformat()
            kept["taken"] = 3
            kept["left"] = 5000
            kept["paused"] = "window"
            kept["at"] = None
            tx.update("watch_run", run.id, {"older_read": kept}, source_intake._MOVED, read_version=current.version)
        assert source_intake.pause_long_reads(store, cfg, NOW) == ["m"]
        waiting = source_intake.older_read_waiting(store.read(), "m")
        assert waiting.get("paused") is None and waiting["taken"] == 3
        assert waiting["left"] == MAIL_IMPORT_MAX_ITEMS - 3
        assert date.fromisoformat(waiting["since"]) == (NOW - timedelta(days=MAIL_IMPORT_MAX_DAYS)).date()
        assert source_intake.pause_long_reads(store, cfg, NOW) == []
    finally:
        pass


def test_starting_the_worker_does_not_pause_an_authorized_read_for_its_width(tmp_path, monkeypatch):
    from engine.config.schema import MAIL_IMPORT_MAX_DAYS
    from engine.worker import Events, Worker

    ws, cfg, store, service = world(tmp_path, monkeypatch, {2: ConnectorError("throttled", "HTTP 429", retry_after=90)})
    source_intake.read_full_now(ws, store, cfg, "m", 14, NOW)
    run = source_intake.intake_run(store.read(), "m")
    with store.transaction() as tx:
        current = tx.get("watch_run", run.id)
        kept = dict(current.data["older_read"])
        wide = (date.fromisoformat(kept["before"]) - timedelta(days=MAIL_IMPORT_MAX_DAYS + 60)).isoformat()
        kept["since"] = wide
        kept["paused"] = "window"
        kept["at"] = None
        tx.update("watch_run", run.id, {"older_read": kept}, source_intake._MOVED, read_version=current.version)
    worker = Worker(ws, store, cfg, Events(), on_restart=lambda: None)
    monkeypatch.setattr(worker, "now", lambda: NOW)
    monkeypatch.setattr(worker, "_start_loop", lambda name: None)
    monkeypatch.setattr(worker, "_start_watchdog", lambda: None)
    for name in (
        "check_readers",
        "settle_acts",
        "check_switch_soon",
        "measure_soon",
        "read_catalogs_soon",
        "note_running",
    ):
        monkeypatch.setattr(worker, name, lambda *a, **k: None)
    worker.start()
    waiting = source_intake.older_read_waiting(store.read(), "m")
    assert waiting.get("paused") is None and waiting["since"] == wide
    assert waiting["at"] == NOW.isoformat()
