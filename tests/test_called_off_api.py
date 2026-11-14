"""The routes behind the called-off line (design 6.33; stories S-0001, S-0002): Call off holds the person's own entry
and its to-dos, the schedule says it is on hold, New date and Drop are the person's own changes with Undo, and a
dropped entry's to-dos are asked about once. Built on the calendar tests' workspace."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.storage import WriteContext
from tests.test_act_calendar import calendar  # noqa: F401, F811  (fixture)
from tests.test_act_draft_api import client  # noqa: F401
from tests.test_publisher import api  # noqa: F401

_DAY = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=5)
START, END = _DAY.isoformat(), (_DAY + timedelta(hours=1)).isoformat()
NEW_START, NEW_END = (_DAY + timedelta(days=1)).isoformat(), (_DAY + timedelta(days=1, hours=1)).isoformat()
_ENGINE = WriteContext(actor="engine", trust="trusted", op="test.called_off")


def make(client, **more) -> tuple[str, str]:  # noqa: F811
    with client.store.transaction() as tx:
        entry = tx.create("event", {"title": "Own note", "start": START, "end": END, "trust": "trusted"}, _ENGINE).id
        todo = tx.create(
            "action", {"text": "Bring the proofs", "owners": [{"person": client.person}], "due_event": entry}, _ENGINE
        ).id
    return entry, todo


def data(client, kind, ident):  # noqa: F811
    return client.store.read().get(kind, ident).data


def test_calling_an_entry_off_holds_it_and_its_todos_and_undo_puts_both_back(calendar):  # noqa: F811
    entry, todo = make(calendar)
    done = calendar.post(f"/api/events/{entry}/call-off")
    assert done.status_code == 200, done.text
    assert data(calendar, "event", entry)["cancelled"] and data(calendar, "action", todo)["on_hold"]["entry"] == entry
    line = [x for x in calendar.get("/api/today/queue").json() if x["kind"] == "called_off"]
    assert line and line[0]["event"] == entry and line[0]["state"] == "own" and line[0]["count"] == 1
    assert calendar.post(f"/api/changesets/{done.json()['changeset']}/undo", json={"ops": None}).status_code == 200
    assert not data(calendar, "event", entry)["cancelled"] and data(calendar, "action", todo)["on_hold"] is None


def test_a_new_date_and_a_drop_are_the_persons_changes_and_the_drop_needs_a_reason(calendar):  # noqa: F811
    entry, todo = make(calendar)
    calendar.post(f"/api/events/{entry}/call-off")
    assert calendar.post(f"/api/events/{entry}/drop", json={"reason": " "}).status_code in (409, 422)
    back = calendar.post(f"/api/events/{entry}/new-date", json={"start": NEW_START, "end": NEW_END})
    assert back.status_code == 200, back.text
    assert not data(calendar, "event", entry)["cancelled"] and data(calendar, "action", todo)["on_hold"] is None
    calendar.post(f"/api/events/{entry}/call-off")
    gone = calendar.post(f"/api/events/{entry}/drop", json={"reason": "Not needed any more"})
    assert gone.status_code == 200, gone.text
    kinds = [x["kind"] for x in calendar.get("/api/today/queue").json()]
    assert "called_off_todos" in kinds and "called_off" not in kinds
    kept = calendar.post(f"/api/events/{entry}/keep-todos")
    assert kept.status_code == 200 and data(calendar, "action", todo)["on_hold"] is None
    assert calendar.post(f"/api/events/{entry}/keep-todos").status_code == 409  # asked once


def test_the_schedule_says_a_called_off_entry_is_on_hold_and_hides_a_dropped_one(calendar):  # noqa: F811
    entry, _ = make(calendar)
    calendar.post(f"/api/events/{entry}/call-off")
    shown = [
        e
        for d in calendar.get("/api/schedule", params={"from": START[:10], "days": 3}).json()["days"]
        for e in d["all_day"] + d["timed"]
        if e["snapshot"] == entry
    ]
    assert shown and shown[0]["cancelled"] and shown[0]["held"]
    calendar.post(f"/api/events/{entry}/drop", json={"reason": "Not needed"})
    again = [
        e
        for d in calendar.get("/api/schedule", params={"from": START[:10], "days": 3}).json()["days"]
        for e in d["all_day"] + d["timed"]
        if e["snapshot"] == entry
    ]
    assert again == []


def test_the_edit_route_changes_the_place_and_repeat_with_undo_and_refuses_a_stale_read(calendar):  # noqa: F811
    entry, _ = make(calendar)
    version = calendar.store.read().get("event", entry).version
    done = calendar.post(
        f"/api/events/{entry}/edit", json={"read_version": version, "where": "Room 4", "repeat": "week"}
    )
    assert done.status_code == 200 and done.json()["changeset"], done.text
    assert data(calendar, "event", entry)["repeat"] == {"every": "week", "until": None}
    stale = calendar.post(f"/api/events/{entry}/edit", json={"read_version": version, "where": "Room 5"})
    assert stale.json() == {"changeset": None, "refused": "changed"}
    bad = calendar.post(
        f"/api/events/{entry}/edit",
        json={"read_version": version + 1, "repeat": "week", "repeat_until": "2001-01-01"},
    )
    assert bad.status_code == 409
    assert calendar.post(f"/api/changesets/{done.json()['changeset']}/undo", json={"ops": None}).status_code == 200
    assert data(calendar, "event", entry).get("repeat") is None
