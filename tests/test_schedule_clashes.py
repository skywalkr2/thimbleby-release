"""The Schedule's clashes come from the same rules as Today's clash lines (design 6.32, 7.7): overlaps and too little
travel time between places, never an all-day entry, and never a pair the person said is fine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.app import create_app
from engine import day_clashes, schedule, suggestions, today_queue
from tests.test_day_capacity import NOW, build, connected, day, meeting


def _pairs(found):
    return [(c.first.item.title, c.second.item.title, c.state, c.minutes) for c in found]


def test_the_schedule_lists_the_clashes_todays_lines_list_and_a_pair_marked_fine_is_not_one_of_them(tmp_path):
    ws, cfg, store = build(tmp_path)
    try:
        travel = cfg.steward.clashes.travel_minutes
        assert travel > 10
        connected(store, "a", "Standup", f"{day(1)}T09:00:00+00:00", f"{day(1)}T09:30:00+00:00")
        connected(store, "b", "Review", f"{day(1)}T09:15:00+00:00", f"{day(1)}T10:00:00+00:00")
        connected(store, "c", "Site visit", f"{day(2)}T10:00:00+00:00", f"{day(2)}T11:00:00+00:00", "North office")
        connected(store, "d", "Supplier call", f"{day(2)}T11:10:00+00:00", f"{day(2)}T12:00:00+00:00", "South office")
        connected(store, "e", "Holiday", day(3), day(4), None)  # a timed entry over an all-day one is no clash
        connected(store, "f", "Workshop", f"{day(3)}T09:00:00+00:00", f"{day(3)}T10:00:00+00:00")
        shown = schedule.clashes(store, cfg, NOW, NOW.date(), 7)
        assert _pairs(shown) == [
            ("Standup", "Review", "overlap", 15),
            ("Site visit", "Supplier call", "travel", travel - 10),
        ]
        assert [c.travel for c in shown] == [travel, travel]
        # The schedule lists the clashes of the lines on Today and no others.
        lines = [x for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "clash"]
        assert [(x.text, x.other, x.state) for x in lines] == [(c[0], c[1], c[2]) for c in _pairs(shown)]
        made = suggestions.put_off(store, cfg, lines[0], NOW)
        assert _pairs(schedule.clashes(store, cfg, NOW, NOW.date(), 7)) == [_pairs(shown)[1]]
        assert suggestions.take_back(store, made)
        assert _pairs(schedule.clashes(store, cfg, NOW, NOW.date(), 7)) == _pairs(shown)
        # Only the days asked for are looked at.
        assert _pairs(schedule.clashes(store, cfg, NOW, NOW.date() + timedelta(days=2), 1)) == [_pairs(shown)[1]]
        # A clash that has ended is still one on the day it was (Today leaves it out, the schedule's past days do not).
        meeting(store, "Early one", f"{day(0)}T07:00:00+00:00", f"{day(0)}T08:00:00+00:00")
        meeting(store, "Early two", f"{day(0)}T07:30:00+00:00", f"{day(0)}T08:30:00+00:00")
        assert ("Early one", "Early two", "overlap", 30) in _pairs(schedule.clashes(store, cfg, NOW, NOW.date(), 1))
        assert all(c.first.item.title != "Early one" for c in day_clashes.upcoming(store, cfg, NOW))
    finally:
        store.close()


def test_the_schedule_answer_carries_the_clashes_with_travel_saying_so_and_leaves_out_a_pair_marked_fine(tmp_path):
    ws, cfg, store = build(tmp_path)
    here_now = datetime.now(UTC).replace(microsecond=0)
    today = here_now.date()

    def at(offset, time):
        return f"{(today + timedelta(days=offset)).isoformat()}T{time}:00+00:00"

    try:
        travel = cfg.steward.clashes.travel_minutes
        connected(store, "a", "Standup", at(1, "09:00"), at(1, "09:30"))
        connected(store, "b", "Review", at(1, "09:15"), at(1, "10:00"))
        connected(store, "c", "Site visit", at(2, "10:00"), at(2, "11:00"), "North office")
        connected(store, "d", "Supplier call", at(2, "11:10"), at(2, "12:00"), "South office")
        connected(store, "e", "Sync", at(3, "09:00"), at(3, "10:00"))
        connected(store, "f", "Lunch", at(3, "09:30"), at(3, "10:30"))
        fine = next(x for x in today_queue.queue(ws, store, cfg, here_now) if x.kind == "clash" and x.text == "Sync")
        suggestions.put_off(store, cfg, fine, here_now)
    finally:
        store.close()
    client = TestClient(create_app(ws, cfg, "t", start_worker=False))
    client.headers["Authorization"] = "Bearer t"
    api = cfg.server.base_path.rstrip("/") + "/api"
    page = client.get(f"{api}/schedule", params={"from": today.isoformat(), "days": 7}).json()
    titles = {e["snapshot"]: e["title"] for d in page["days"] for e in d["timed"]}
    starts = {e["snapshot"]: e["start"] for d in page["days"] for e in d["timed"]}
    got = [
        (titles[c["first"]["snapshot"]], titles[c["second"]["snapshot"]], c["kind"], c["minutes"], c["travel_minutes"])
        for c in page["clashes"]
    ]
    assert got == [
        ("Standup", "Review", "overlap", 15, travel),
        ("Site visit", "Supplier call", "travel", travel - 10, travel),
    ]
    first = page["clashes"][0]
    assert (
        first["first"]["start"] == starts[first["first"]["snapshot"]]
        and first["day"] == (today + timedelta(days=1)).isoformat()
    )
    # The pair marked fine is two ordinary entries: both are still on the day, and no clash names them.
    assert {"Sync", "Lunch"} <= set(titles.values())


def test_the_timeline_carries_the_clashes_of_its_whole_range_and_not_one_marked_fine(tmp_path):
    from engine import timeline

    ws, cfg, store = build(tmp_path)
    try:
        connected(store, "a", "Standup", f"{day(1)}T09:00:00+00:00", f"{day(1)}T09:30:00+00:00")
        connected(store, "b", "Review", f"{day(1)}T09:15:00+00:00", f"{day(1)}T10:00:00+00:00")
        # Beyond the longest run of days the schedule's own read allows.
        far = schedule.MOST_DAYS + 10
        connected(store, "c", "Late one", f"{day(far)}T09:00:00+00:00", f"{day(far)}T10:00:00+00:00")
        connected(store, "d", "Late two", f"{day(far)}T09:30:00+00:00", f"{day(far)}T10:30:00+00:00")
        found = timeline.timeline(store, cfg, NOW, NOW.date(), "quarter")
        assert _pairs(found.clashes) == [
            ("Standup", "Review", "overlap", 15),
            ("Late one", "Late two", "overlap", 30),
        ]
        # A shorter range holds only its own.
        short = timeline.timeline(store, cfg, NOW, NOW.date(), "two_weeks")
        assert _pairs(short.clashes) == [("Standup", "Review", "overlap", 15)]
        line = next(x for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "clash" and x.text == "Standup")
        suggestions.put_off(store, cfg, line, NOW)
        again = timeline.timeline(store, cfg, NOW, NOW.date(), "quarter")
        assert _pairs(again.clashes) == [("Late one", "Late two", "overlap", 30)]
    finally:
        store.close()


def test_a_timeline_with_nothing_clashing_carries_no_clashes(tmp_path):
    from engine import timeline

    ws, cfg, store = build(tmp_path)
    try:
        connected(store, "a", "Standup", f"{day(1)}T09:00:00+00:00", f"{day(1)}T09:30:00+00:00")
        assert timeline.timeline(store, cfg, NOW, NOW.date(), "two_weeks").clashes == []
    finally:
        store.close()


def _four_that_overlap(store):
    """The reviewer's four: one meeting runs into three others, two of them into each other (four pairs, one group)."""
    connected(store, "a", "Venue walk", f"{day(1)}T09:00:00+00:00", f"{day(1)}T10:30:00+00:00")
    connected(store, "b", "Catering call", f"{day(1)}T09:30:00+00:00", f"{day(1)}T10:00:00+00:00")
    connected(store, "c", "Budget check", f"{day(1)}T09:45:00+00:00", f"{day(1)}T10:15:00+00:00")
    connected(store, "d", "Supplier call", f"{day(1)}T10:15:00+00:00", f"{day(1)}T11:00:00+00:00")
    connected(store, "e", "Dentist", f"{day(2)}T09:00:00+00:00", f"{day(2)}T10:00:00+00:00")
    connected(store, "f", "Gym", f"{day(2)}T09:30:00+00:00", f"{day(2)}T10:30:00+00:00")


def test_pairs_that_share_a_meeting_are_one_clash_everywhere_clashes_are_counted(tmp_path):
    ws, cfg, store = build(tmp_path)
    try:
        _four_that_overlap(store)
        pairs = schedule.clashes(store, cfg, NOW, NOW.date(), 7)
        assert len(pairs) == 5
        groups = day_clashes.groups(pairs)
        assert [g.members for g in groups] == [4, 2]
        assert [len(g.pairs) for g in groups] == [4, 1]
        # Today has one line for each group, saying how many meetings are in it.
        lines = [x for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "clash"]
        assert [(x.key, x.count) for x in lines] == [(g.key, g.members) for g in groups]
        # The line names its first pair; the other meetings of the group are its parts, so its details list all four.
        assert sorted(part.text for part in lines[0].items) == ["Budget check", "Supplier call"]
        assert lines[1].items == []
        pairs_seen = [(g.key, g.pair_keys) for g in groups]
    finally:
        store.close()
    # The schedule's answer names the group of every pair, so the screens count the same clashes the same way.
    client = TestClient(create_app(ws, cfg, "t", start_worker=False))
    client.headers["Authorization"] = "Bearer t"
    api = cfg.server.base_path.rstrip("/") + "/api"
    got = client.get(f"{api}/schedule", params={"from": NOW.date().isoformat(), "days": 7}).json()["clashes"]
    assert len(got) == 5
    assert {c["group"] for c in got} == {key for key, _ in pairs_seen}


def test_saying_a_group_of_clashes_is_fine_clears_every_pair_of_it_and_no_other(tmp_path):
    ws, cfg, store = build(tmp_path)
    try:
        _four_that_overlap(store)
        lines = [x for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "clash"]
        made = suggestions.put_off(store, cfg, lines[0], NOW)
        left = day_clashes.groups(schedule.clashes(store, cfg, NOW, NOW.date(), 7))
        assert [g.members for g in left] == [2]
        assert [x.count for x in today_queue.queue(ws, store, cfg, NOW) if x.kind == "clash"] == [2]
        assert suggestions.take_back(store, made)
        assert [g.members for g in day_clashes.groups(schedule.clashes(store, cfg, NOW, NOW.date(), 7))] == [4, 2]
    finally:
        store.close()
