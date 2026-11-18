"""Old data is a failure (S-0649): a source whose own data is older than its normal refresh is one Today line and is
never read as "no changes", and the read that finds fresh data after it files what was missed as one catch-up item. The
stand-in source says when its data was made, as a connector that knows it does."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import yaml
from fastapi.testclient import TestClient

from api.app import create_app
from engine.config import load_config
from engine.today_queue import queue
from engine.watch import refresh
from tests.test_today_dashboard import event
from tests.test_watch import NOW, make


def sources(items=(), made=None, **more):
    settings = {"items": list(items), **({"generated_at": made.isoformat()} if made else {})}
    return [{"id": "s", "connector": "fake", "label": "Board", "first_run": "all", "settings": settings, **more}]


def lines(ws, store, cfg, now):
    return [line for line in queue(ws, store, cfg, now) if line.kind == "source_unread"]


def test_data_stamped_weeks_old_is_one_line_naming_its_age_and_never_no_changes(tmp_path):
    ws, cfg, store = make(tmp_path, sources(made=NOW - timedelta(days=20)))
    try:
        result = refresh(ws, store, cfg, "s", NOW)
        assert (result.outcome, result.new, result.changed, result.removed) == ("ok", [], [], [])
        (line,) = lines(ws, store, cfg, NOW)
        assert (line.source, line.problem_kind, line.days_old) == ("s", "old_data", 20)
    finally:
        store.close()


def test_the_connections_list_and_the_queue_serve_the_age_on_the_real_clock(tmp_path):
    now = datetime.now(UTC)
    ws, cfg, store = make(tmp_path, sources(made=now - timedelta(days=20)))
    try:
        refresh(ws, store, cfg, "s", now)
    finally:
        store.close()
    client = TestClient(create_app(ws, cfg, "t", start_worker=False), headers={"Authorization": "Bearer t"})
    api = cfg.server.base_path.rstrip("/") + "/api"
    [shown] = client.get(f"{api}/watch").json()
    assert shown["old_data_days"] == 20  # the screen words its last read from this, never as "Nothing new"
    served = [x for x in client.get(f"{api}/today/queue").json() if x["kind"] == "source_unread"]
    assert [(x["problem_kind"], x["days_old"]) for x in served] == [("old_data", 20)]


def test_fresh_data_and_a_source_that_says_no_time_are_not_old(tmp_path):
    for made in (NOW - timedelta(hours=1), None):
        ws, cfg, store = make(tmp_path / str(bool(made)), sources(made=made))
        try:
            refresh(ws, store, cfg, "s", NOW)
            assert lines(ws, store, cfg, NOW) == []
        finally:
            store.close()


def test_the_normal_refresh_is_a_setting_of_the_source(tmp_path):
    ws, cfg, store = make(tmp_path, sources(made=NOW - timedelta(days=20), data_fresh_hours=24 * 30))
    try:
        refresh(ws, store, cfg, "s", NOW)
        assert lines(ws, store, cfg, NOW) == []  # twenty days is within this source's own thirty
    finally:
        store.close()


def test_thirty_differences_after_old_data_become_one_catch_up_item_that_lists_them(tmp_path):
    ws, cfg, store = make(tmp_path, sources(made=NOW - timedelta(days=20)))
    try:
        refresh(ws, store, cfg, "s", NOW)
        meetings = [event(f"m{n}", f"2030-03-{5 + n % 20:02d}T09:00:00+00:00") for n in range(30)]
        (ws.config_dir / "watch.yaml").write_text(
            yaml.safe_dump({"version": 1, "sources": sources(meetings, NOW + timedelta(hours=1))})
        )
        later = NOW + timedelta(hours=2)
        fresh = load_config(ws.config_dir, env={})
        result = refresh(ws, store, fresh, "s", later)
        assert len(result.new) == 1
        request = store.read().get("request", result.new[0])
        source = store.read().get("source", request.data["source"])
        text = (ws.sources_dir / f"{source.data['content_hash']}.txt").read_text()
        assert all(f"Event m{n}" in text for n in range(30))
        assert lines(ws, store, fresh, later) == []  # the line goes once the data is fresh
    finally:
        store.close()


def test_the_same_thirty_meetings_after_fresh_data_stay_one_input_each(tmp_path):
    ws, cfg, store = make(tmp_path, sources(made=NOW - timedelta(hours=1)))
    try:
        refresh(ws, store, cfg, "s", NOW)
        meetings = [event(f"m{n}", f"2030-03-{5 + n % 20:02d}T09:00:00+00:00") for n in range(30)]
        (ws.config_dir / "watch.yaml").write_text(
            yaml.safe_dump({"version": 1, "sources": sources(meetings, NOW + timedelta(hours=1))})
        )
        result = refresh(ws, store, load_config(ws.config_dir, env={}), "s", NOW + timedelta(hours=2))
        assert len(result.new) == 30
    finally:
        store.close()


def test_a_calendar_file_and_a_calendar_link_say_when_their_data_was_made(tmp_path, monkeypatch):
    import os

    from engine.connectors import ConnectorContext, checked_poll
    from engine.connectors.calendar import CalendarSettings, read_calendar

    calendar = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//example//EN\nEND:VCALENDAR\n"
    path = tmp_path / "calendar.ics"
    path.write_text(calendar)
    made = NOW - timedelta(days=20)
    os.utime(path, (made.timestamp(), made.timestamp()))
    context = ConnectorContext(tmp_path, now=NOW, timezone="UTC")
    poll = checked_poll(read_calendar(CalendarSettings(file=str(path)), {}, context))
    assert datetime.fromisoformat(poll.generated_at) == made

    import httpx

    import engine.net

    monkeypatch.setenv("CAL_ADDRESS", "https" + "://calendar.example.com/a.ics")
    monkeypatch.setattr(
        engine.net,
        "TRANSPORT",
        httpx.MockTransport(
            lambda _r: httpx.Response(200, text=calendar, headers={"Last-Modified": "Mon, 01 Jan 2029 10:00:00 GMT"})
        ),
    )
    poll = checked_poll(read_calendar(CalendarSettings(address="env:CAL_ADDRESS"), {}, context))
    assert datetime.fromisoformat(poll.generated_at) == datetime(2029, 1, 1, 10, tzinfo=UTC)
