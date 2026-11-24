"""A day is never taken by cutting a timestamp (S-0689): the person's own day comes from one helper, and a check
refuses `[:10]` in the engine and the API."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.absence import _days, window_of
from engine.connectors import EventDetails
from engine.local_day import day_of, day_text, maybe_day

EASTERN = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent


def test_a_time_written_in_utc_is_the_day_where_the_person_is():
    assert day_of("2026-11-24T01:00:00Z", EASTERN) == date(2026, 11, 23)  # Monday 8 PM Eastern
    assert day_text("2026-11-24T01:00:00+00:00", EASTERN) == "2026-11-23"
    assert day_of("2026-11-24T01:00:00", EASTERN) == date(2026, 11, 24)  # no offset: written where they are
    assert day_of("2026-11-24", EASTERN) == date(2026, 11, 24)
    assert day_of(datetime(2026, 11, 24, 1, tzinfo=UTC), EASTERN) == date(2026, 11, 23)
    assert maybe_day("not a day", EASTERN) is None and maybe_day(None, EASTERN) is None


def test_an_out_of_office_ending_friday_midnight_eastern_leaves_thursday_the_last_day():
    details = EventDetails(start="2026-11-24T05:00:00Z", end="2026-11-27T05:00:00Z")
    first, last = _days(details, details.start, details.end, EASTERN)
    assert (first, last) == (date(2026, 11, 24), date(2026, 11, 26))  # Tuesday to Thursday, Friday is back


def test_the_read_window_starts_on_the_persons_day_in_the_evening():
    settings = type("S", (), {"days_back": 0, "days_ahead": 1})()
    evening = datetime(2026, 11, 24, 2, 0, tzinfo=UTC)  # Monday 9 PM Eastern
    assert window_of(settings, evening, EASTERN) == (date(2026, 11, 23), date(2026, 11, 24))
    assert window_of(settings, evening + timedelta(hours=12), EASTERN)[0] == date(2026, 11, 24)


def test_no_engine_or_api_code_cuts_ten_characters_off_a_timestamp():
    found = []
    for folder in ("engine", "api"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"\[:10\]", line):
                    found.append(f"{path.relative_to(ROOT)}:{number}")
    assert found == [], "turn a timestamp into the person's day with engine.local_day, never by slicing: " + ", ".join(
        found
    )


def test_no_screen_code_cuts_ten_characters_off_a_timestamp():
    """S-0726: the web takes a day through the shared date helpers (`clockDay`, `writtenDay`), never by slicing."""
    found = []
    for path in sorted((ROOT / "web" / "src").rglob("*.ts*")):
        if ".test." in path.name or path.name == "test-utils.tsx":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\.(?:slice|substring|substr)\(\s*0\s*,\s*10\s*\)", line):
                found.append(f"{path.relative_to(ROOT)}:{number}")
    assert found == [], "take a day with the date helpers in web/src/lib/dates.ts, never by slicing: " + ", ".join(
        found
    )


# ---- the places that took a day from a timestamp (S-0689) ----------------------------------------------------------


def _store(tmp_path, clock=None):
    from engine.storage import Store
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    cfg.workspace.user.timezone = "America/New_York"
    return cfg, Store(ws.db_path, cfg=cfg, **({"clock": clock} if clock else {}))


def test_a_promise_tied_to_a_monday_8_pm_meeting_written_in_utc_is_due_monday(tmp_path):
    from engine.applier import _event_day
    from engine.storage import WriteContext
    from tests.conftest import DEMO_B, fixture_records

    cfg, store = _store(tmp_path)
    try:
        project = fixture_records(DEMO_B, "project")[0]["id"]
        with store.transaction() as tx:
            made = tx.create(
                "event",
                {
                    "title": "Review",
                    "start": "2026-11-24T01:00:00Z",
                    "end": None,
                    "project": project,
                    "trust": "trusted",
                },
                WriteContext("pm", "trusted", "test"),
            ).id
        with store.transaction() as tx:
            assert _event_day(tx, made, cfg) == date(2026, 11, 23)
    finally:
        store.close()


def test_work_completed_at_9_pm_local_shows_that_day_on_the_record_page(tmp_path):
    from engine.record_page import page
    from engine.storage import WriteContext
    from tests.conftest import DEMO_B, fixture_records

    cfg, store = _store(tmp_path, clock=lambda: "2026-11-24T02:00:00+00:00")  # Monday 9 PM Eastern
    try:
        project = fixture_records(DEMO_B, "project")[0]["id"]
        person = fixture_records(DEMO_B, "person")[0]["id"]
        writer = WriteContext("pm", "trusted", "test")
        with store.transaction() as tx:
            made = tx.create(
                "action",
                {"text": "Send it", "owners": [{"person": person}], "project": project, "status": "open"},
                writer,
            )
        with store.transaction() as tx:
            tx.update("action", made.id, {"status": "done", "done_by": [person]}, writer, read_version=made.version)
        shown = page(store, "project", project, pm=person, here=EASTERN, cfg=cfg)
        assert [c["done_on"] for c in shown["completed_actions"] if c["id"] == made.id] == ["2026-11-23"]
    finally:
        store.close()
