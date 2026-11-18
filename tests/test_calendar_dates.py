"""A calendar date is a date with no time and no zone (S-0650): a to-do's due day and an all-day event stay on their
day whatever zone the person's clock, the computer or the calendar is in. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.schedule import schedule
from engine.storage import WriteContext
from engine.watch import refresh
from engine.workspace import init_workspace
from tests import test_today_dashboard
from tests.conftest import DEMO_B, fixture_records
from tests.test_today_dashboard import event, make
from tests.test_watch import NOW

ZONES = ["Pacific/Honolulu", "America/New_York", "America/Chicago", "America/Los_Angeles", "Pacific/Auckland"]
_TEST = WriteContext(actor="pm", trust="trusted", op="test.calendar-dates")
PERSON = fixture_records(DEMO_B, "person")[0]["id"]


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("sent", ["2030-03-23", "2030-03-23T00:00:00", "2030-03-23T00:00:00-04:00"])
def test_a_due_day_sent_to_the_api_is_the_same_day_in_any_zone(tmp_path, zone, sent):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(
        env={}, flags={"server.base_path": "/", "storage.backups.automatic": False, "workspace.user.timezone": zone}
    )
    app = create_app(ws, cfg, "t", ui_dist=tmp_path / "no-ui", start_worker=False)
    headers = {"Authorization": "Bearer t"}
    with TestClient(app, headers=headers, base_url=f"http://127.0.0.1:{cfg.server.port}") as client:
        store = app.state.store
        with store.transaction() as tx:
            record = tx.create(
                "action", {"text": "Pay it", "owners": [{"person": PERSON}], "due": None, "status": "open"}, _TEST
            ).id
        version = store.read().get("action", record).version
        done = client.post(
            "/api/records/edit", json={"kind": "action", "id": record, "fields": {"due": sent}, "read_version": version}
        )
        assert done.status_code == 200, done.text
        assert store.read().get("action", record).data["due"] == "2030-03-23"


@pytest.mark.parametrize("zone", ZONES)
def test_an_all_day_event_stays_on_its_day_in_any_zone_of_the_person(tmp_path, monkeypatch, zone):
    monkeypatch.setattr(test_today_dashboard, "ZONE", zone)
    ws, cfg, store = make(tmp_path, [event("all", "2030-03-04", "2030-03-06", all_day=True)])
    refresh(ws, store, cfg, "s", NOW)
    days = schedule(store, cfg, NOW, start=date(2030, 3, 3), days=5)
    on = {d.date.isoformat(): [e.item.title for e in d.all_day] for d in days}
    assert on == {
        "2030-03-03": [],
        "2030-03-04": ["Event all"],
        "2030-03-05": ["Event all"],
        "2030-03-06": [],
        "2030-03-07": [],
    }


def _calendar(zone: str | None, *events: str) -> str:
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//example//EN"]
    if zone:
        head.append(f"X-WR-TIMEZONE:{zone}")
    return "\n".join([*head, *events, "END:VCALENDAR"])


_ALL_DAY = "\n".join(
    [
        "BEGIN:VEVENT",
        "UID:day@calendar.example.com",
        "DTSTAMP:20300301T080000Z",
        "SUMMARY:Closed",
        "DTSTART;VALUE=DATE:20300323",
        "DTEND;VALUE=DATE:20300324",
        "END:VEVENT",
    ]
)


@pytest.mark.parametrize("calendar_zone", [None, *ZONES])
@pytest.mark.parametrize("person_zone", ZONES)
def test_an_all_day_event_read_from_a_calendar_in_another_zone_stays_on_its_day(calendar_zone, person_zone):
    from datetime import UTC, datetime

    from engine.connectors.calendar import items

    now = datetime(2030, 3, 20, 12, 0, tzinfo=UTC)
    [found] = items(_calendar(calendar_zone, _ALL_DAY), now, 7, 30, zone=person_zone)
    assert (found.event.all_day, found.event.start, found.event.end) == (True, "2030-03-23", "2030-03-24")


@pytest.mark.parametrize(
    ("zone", "day"), [("Pacific/Auckland", date(2030, 3, 5)), ("Pacific/Honolulu", date(2030, 3, 4))]
)
def test_the_first_result_counts_from_the_persons_own_day_not_the_computers(zone, day):
    from types import SimpleNamespace

    from engine.first_promises import _today

    cfg = SimpleNamespace(workspace=SimpleNamespace(user=SimpleNamespace(timezone=zone)))
    store = SimpleNamespace(clock=lambda: "2030-03-04T23:30:00+00:00")
    assert _today(store, cfg) == day
