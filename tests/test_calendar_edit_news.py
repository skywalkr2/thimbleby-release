"""A calendar item is judged by when it last changed, never by the day of the meeting (S-0760): an edit made now to a
meeting of last week is filed as a change, and an unchanged meeting next week is not, whatever carries the time: a
calendar file, a calendar link or an add-on's calendar (items with `changed_at`). It guards the older-copy and
stale-data rules (S-0685, S-0723)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from email.utils import format_datetime

import httpx
import yaml

import engine.net
from engine.config import load_config
from engine.storage import Store
from engine.watch import refresh
from tests.test_watch import NOW, make

LAST_WEEK = NOW - timedelta(days=7)
NEXT_WEEK = NOW + timedelta(days=7)


def _day(moment: datetime) -> str:
    return moment.strftime("%Y%m%d")


def event(uid: str, title: str, when: datetime, description: str) -> str:
    return "\n".join(
        [
            "BEGIN:VEVENT",
            f"UID:{uid}@calendar.example.com",
            "DTSTAMP:20300301T080000Z",
            f"DTSTART:{_day(when)}T150000Z",
            f"DTEND:{_day(when)}T160000Z",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
        ]
    )


def calendar(*events: str) -> str:
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Fictional//Calendar//EN\n" + "\n".join(events) + "\nEND:VCALENDAR\n"


def both(description: str) -> str:
    return calendar(
        event("past", "Review of the budget", LAST_WEEK, description),
        event("future", "Planning session", NEXT_WEEK, "Bring the agenda and the numbers"),
    )


def _source(settings: dict) -> dict:
    return {
        "id": "s",
        "connector": "calendar",
        "label": "Work calendar",
        "first_run": "baseline",
        "settings": {"days_back": 30, "days_ahead": 30, "expand_days": 60, **settings},
    }


def test_a_calendar_file_edited_now_files_the_meeting_of_last_week_and_not_the_unchanged_one_next_week(tmp_path):
    path = tmp_path / "work.ics"
    ws, cfg, store = make(tmp_path, [_source({"file": str(path)})])
    try:

        def put(text, at):
            path.write_text(text)
            os.utime(path, (at.timestamp(), at.timestamp()))
            return refresh(ws, store, cfg, "s", at)

        put(both("Go through the open invoices"), NOW - timedelta(hours=2))
        # Only the meeting of last week is edited; the file's time is now.
        edited = put(both("Go through the open invoices and the new quote"), NOW)
        assert len(edited.changed) == 1
        # The same file again, touched later: nothing changed, so nothing is filed, however far off the meetings are.
        touched = put(both("Go through the open invoices and the new quote"), NOW + timedelta(hours=1))
        assert (touched.new, touched.changed, touched.removed) == ([], [], [])
    finally:
        store.close()


def test_a_calendar_link_edited_now_files_the_meeting_of_last_week_and_not_the_unchanged_one_next_week(
    tmp_path, monkeypatch
):
    served = {}

    def answer(_request):
        return httpx.Response(
            200, text=served["text"], headers={"Last-Modified": format_datetime(served["at"], usegmt=True)}
        )

    monkeypatch.setenv("CAL_ADDRESS", "https" + "://calendar.example.com/work.ics")
    monkeypatch.setattr(engine.net, "TRANSPORT", httpx.MockTransport(answer))
    ws, cfg, store = make(tmp_path, [_source({"address": "env:CAL_ADDRESS"})])
    try:

        def get(text, at):
            served.update(text=text, at=at)
            return refresh(ws, store, cfg, "s", at)

        get(both("Go through the open invoices"), NOW - timedelta(hours=2))
        edited = get(both("Go through the open invoices and the new quote"), NOW)
        assert len(edited.changed) == 1
        same = get(both("Go through the open invoices and the new quote"), NOW + timedelta(hours=1))
        assert (same.new, same.changed, same.removed) == ([], [], [])
    finally:
        store.close()


def test_an_add_ons_calendar_items_are_judged_by_changed_at_not_by_the_meeting_day(tmp_path):
    def item(key, when, text, changed):
        start = when.replace(hour=15, minute=0).isoformat()
        end = when.replace(hour=16, minute=0).isoformat()
        return {
            "key": key,
            "title": key,
            "text": text,
            "changed_at": changed.isoformat(),
            "event": {"start": start, "end": end, "entries": True},
        }

    ws, cfg, store = make(tmp_path, [])
    try:

        def read(items, at):
            nonlocal store
            store.close()
            current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
            current["sources"] = [
                {
                    "id": "s",
                    "connector": "fake",
                    "label": "Calendar",
                    "first_run": "baseline",
                    "settings": {"items": items},
                }
            ]
            (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
            fresh = load_config(ws.config_dir, env={})
            store = Store(ws.db_path, cfg=fresh)
            return refresh(ws, store, fresh, "s", at)

        long_ago = NOW - timedelta(days=20)
        past = item("past", LAST_WEEK, "Go through the open invoices", long_ago)
        future = item("future", NEXT_WEEK, "Bring the agenda and the numbers", long_ago)
        read([past, future], NOW - timedelta(hours=2))
        edited_past = item("past", LAST_WEEK, "Go through the open invoices and the new quote", NOW)
        edited = read([edited_past, future], NOW)
        assert len(edited.changed) == 1
        again = read([edited_past, future], NOW + timedelta(hours=1))
        assert (again.new, again.changed, again.removed) == ([], [], [])
    finally:
        store.close()
