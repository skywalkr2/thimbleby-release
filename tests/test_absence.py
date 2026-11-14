"""A calendar that holds who is away (design 5.1 "Away periods from an absence calendar"; stories S-0109, S-0110).

A calendar source marked `holds: absence` keeps no calendar entries and hands nothing to the assistant: rules read
each of its entries into a period on the person it names, with the first and last day, an away word as the label, and
the source and entry it came from. One person is written (with Undo); several are asked once per series; nobody known
is counted on the source's row. A later read moves or removes the period, an entry outside the read's window is not
gone, and a period the person edited or removed is theirs. A typed list and a handed-in out-of-office reply go through
`person.away` (tests/test_days_off.py). Names come from the fictional workspace's records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from engine.applier import apply_as_person, undo
from engine.config import load_config
from engine.storage import Store, StoreError, WriteContext
from engine.watch import refresh, unmatched_names
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)
_TEST = WriteContext("pm", "trusted", "test")
PEOPLE = {p["id"]: p for p in fixture_records(DEMO_B, "person")}
PM = "PER-1"
FULL, INITIAL, ALIAS = "PER-6", "PER-4", "PER-5"  # a full name, a first name with an initial, an alias
OTHER = "PER-3"
EMPTY = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Fictional//Calendar//EN\nEND:VCALENDAR\n"


def name(pid):
    return PEOPLE[pid]["full_name"]


def first_and_initial(pid):
    first, *rest = name(pid).split()
    return f"{first} {rest[-1][0]}."


def vevent(uid, title, *, start="20300311", end="20300314", all_day=True, organizer=None, attendees=(), status=None):
    if all_day:
        lines = [f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}"]
    else:
        lines = [f"DTSTART:{start}T090000Z", f"DTEND:{end}T170000Z"]
    head = ["BEGIN:VEVENT", f"UID:{uid}@calendar.example.com", "DTSTAMP:20300301T080000Z", f"SUMMARY:{title}"]
    more = [f"STATUS:{status}"] if status else []
    if organizer:
        more.append(f"ORGANIZER;CN={name(organizer)}:mailto:{organizer.lower()}@example.com")
    for pid in attendees:
        more.append(f"ATTENDEE;CN={name(pid)};PARTSTAT=ACCEPTED:mailto:{pid.lower()}@example.com")
    return "\n".join([*head, *lines, *more, "END:VEVENT"])


def calendar(*events):
    head = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Fictional//Calendar//EN\n"
    return head + "\n".join(events) + "\nEND:VCALENDAR\n"


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "away.ics"
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    source = {
        "id": "away",
        "connector": "calendar",
        "label": "Who is away",
        "holds": "absence",
        "settings": {"file": str(path), "days_ahead": 30, "days_back": 1},
    }
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": [source]}))
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    with store.transaction() as tx:
        for pid, address in (("PER-3", "per-3@example.com"), ("PER-4", "per-4@example.com")):
            found = tx.get("person", pid)
            tx.update(
                "person",
                pid,
                {"how_to_reach": {"email": [address]}},
                _TEST,
                read_version=found.version,
            )

    def put(text, at=NOW):
        path.write_text(text)
        return refresh(ws, store, cfg, "away", at)

    yield ws, cfg, store, put
    store.close()


def away_of(store, pid):
    return store.read().get("person", pid).data.get("away") or []


def test_the_source_is_read_into_days_away_with_no_entry_no_run_and_only_the_days_kept(env):
    ws, cfg, store, put = env
    result = put(calendar(vevent("a", f"{name(FULL)} - vacation (Lisbon, flights booked)")))
    assert (result.outcome, result.new) == ("ok", [])
    (period,) = away_of(store, FULL)
    # An all-day entry's end is exclusive: the 11th to the 14th is the 11th to the 13th.
    assert (str(period["start"]), str(period["end"]), period["label"]) == ("2030-03-11", "2030-03-13", "vacation")
    assert period["read"]["source"] == "away" and period["read"]["entry"]
    # Nothing but the days, an away word and where it came from is kept: no title, no place, no calendar entry, no run.
    assert "Lisbon" not in str(store.read().get("person", FULL).data)
    assert store.read().list("event") == [] and store.read().list("snapshot") == []
    # The only request is the change's own record; nothing was handed to the assistant.
    assert [r.data["origin"] for r in store.read().list("request")] == ["schedule"]
    assert store.read().list("run") == []


@pytest.mark.parametrize(
    "title",
    [
        lambda: f"{name(FULL)} on leave",
        lambda: f"{first_and_initial(INITIAL)} out of office",
        lambda: f"{PEOPLE[ALIAS]['aliases'][0]}: vacation",
    ],
)
def test_a_full_name_a_first_name_with_an_initial_and_an_alias_each_name_one_person(env, title):
    ws, cfg, store, put = env
    put(calendar(vevent("a", title())))
    who = [pid for pid in (FULL, INITIAL, ALIAS) if away_of(store, pid)]
    assert len(who) == 1


def test_a_first_name_alone_names_nobody_and_a_label_comes_only_from_an_away_word(env):
    ws, cfg, store, put = env
    put(calendar(vevent("a", f"{name(INITIAL).split()[0]} is somewhere nice")))
    assert all(not away_of(store, pid) for pid in PEOPLE)
    put(calendar(vevent("b", f"{name(FULL)} at the conference")))
    (period,) = away_of(store, FULL)
    assert period["label"] is None


def test_an_entry_with_no_name_in_its_title_goes_to_the_one_person_asked_else_the_organizer(env):
    ws, cfg, store, put = env
    put(
        calendar(
            vevent("a", "Vacation", attendees=(INITIAL,)),
            vevent("b", "Out of office", start="20300320", end="20300321", organizer=FULL),
        )
    )
    assert len(away_of(store, INITIAL)) == 1 and len(away_of(store, FULL)) == 1


def test_a_timed_entry_counts_its_days_whole(env):
    ws, cfg, store, put = env
    put(calendar(vevent("a", f"{name(FULL)} away", start="20300312", end="20300313", all_day=False)))
    (period,) = away_of(store, FULL)
    assert (str(period["start"]), str(period["end"])) == ("2030-03-12", "2030-03-13")


def test_nobody_known_writes_nothing_asks_nothing_and_the_name_is_counted_for_the_row(env):
    ws, cfg, store, put = env
    put(
        calendar(
            vevent("a", "Quentin Zabriskie - vacation"), vevent("b", "Quentin Zabriskie - leave", start="20300320")
        )
    )
    assert all(not away_of(store, pid) for pid in PEOPLE)
    assert [q for q in store.read().list("question") if (q.data.get("resolves") or {}).get("kind") == "away"] == []
    assert unmatched_names(store, "away") == ["Quentin Zabriskie"]


def test_several_people_are_asked_once_per_series_and_the_answer_writes_the_period_with_undo(env):
    from engine import absence

    ws, cfg, store, put = env
    feed = calendar(vevent("a", f"{name(FULL)} and {name(OTHER)} vacation"))
    put(feed)
    put(feed)  # read again: still one question
    asked = [q for q in store.read().list("question") if (q.data.get("resolves") or {}).get("kind") == "away"]
    assert len(asked) == 1 and sorted(asked[0].data["options"]) == sorted([FULL, OTHER])
    assert all(not away_of(store, pid) for pid in PEOPLE)
    with pytest.raises(Exception, match="listed"):
        absence.answer(store, cfg, asked[0].id, INITIAL)
    changeset = absence.answer(store, cfg, asked[0].id, OTHER)
    assert len(away_of(store, OTHER)) == 1 and not away_of(store, FULL)
    assert store.read().get("question", asked[0].id).data["status"] == "answered"
    put(feed)  # the answer stands: nothing asked again, nothing duplicated
    assert len(away_of(store, OTHER)) == 1
    undo(store, changeset)
    assert not away_of(store, OTHER)


def test_a_later_read_moves_the_period_and_a_called_off_entry_removes_it(env):
    ws, cfg, store, put = env
    put(calendar(vevent("a", f"{name(FULL)} vacation")))
    put(calendar(vevent("a", f"{name(FULL)} vacation", end="20300316")))
    (period,) = away_of(store, FULL)
    assert str(period["end"]) == "2030-03-15" and period["read"]["end"] == "2030-03-15"
    put(calendar(vevent("a", f"{name(FULL)} vacation", end="20300316", status="CANCELLED")))
    assert away_of(store, FULL) == []


def test_an_entry_outside_the_reads_window_is_not_gone_but_one_inside_it_is(env):
    ws, cfg, store, put = env
    feed = calendar(
        vevent("near", f"{name(FULL)} vacation", start="20300306", end="20300308"),
        vevent("also", f"{name(INITIAL)} vacation", start="20300306", end="20300308"),
    )
    put(feed)
    assert len(away_of(store, FULL)) == 1 and len(away_of(store, INITIAL)) == 1
    # Ten days later both entries are before the read's window, so the calendar no longer lists them: not gone.
    put(feed, NOW + timedelta(days=10))
    assert len(away_of(store, FULL)) == 1 and len(away_of(store, INITIAL)) == 1
    # One that is still inside the window and is no longer listed is gone.
    put(feed, NOW + timedelta(days=1))
    put(
        calendar(vevent("also", f"{name(INITIAL)} vacation", start="20300306", end="20300308")), NOW + timedelta(days=1)
    )
    assert away_of(store, FULL) == [] and len(away_of(store, INITIAL)) == 1


def test_a_period_the_person_edited_or_removed_is_theirs_and_no_read_changes_it(env):
    ws, cfg, store, put = env
    put(calendar(vevent("a", f"{name(FULL)} vacation"), vevent("b", f"{name(INITIAL)} vacation", start="20300320")))
    with store.transaction() as tx:
        found = tx.get("person", FULL)
        away = [{**found.data["away"][0], "end": "2030-03-20"}]
        tx.update("person", FULL, {"away": away}, _TEST, read_version=found.version)
        other = tx.get("person", INITIAL)
        tx.update("person", INITIAL, {"away": []}, _TEST, read_version=other.version)
    # The feed moves the first and the second is still listed; neither is touched.
    put(
        calendar(
            vevent("a", f"{name(FULL)} vacation", end="20300316"),
            vevent("b", f"{name(INITIAL)} vacation", start="20300320"),
        )
    )
    assert str(away_of(store, FULL)[0]["end"]) == "2030-03-20"
    assert away_of(store, INITIAL) == []
    put(calendar())  # and an entry gone from the feed doesn't take the edited period away
    assert len(away_of(store, FULL)) == 1


def test_a_read_that_finds_nothing_new_writes_no_change(env):
    ws, cfg, store, put = env
    feed = calendar(vevent("a", f"{name(FULL)} vacation"))
    put(feed)
    before = len(store.read().list("changeset"))
    put(feed, NOW + timedelta(hours=1))
    assert len(store.read().list("changeset")) == before


def test_a_source_holds_meetings_unless_it_is_marked(env):
    ws, cfg, store, put = env
    assert cfg.watch.sources[0].holds == "absence"
    from engine.config.schema import WatchSource

    assert WatchSource(id="x", connector="calendar").holds == "meetings"


# ---- who may write a period this way ---------------------------------------------------------------------------


def test_only_the_engines_own_reading_may_write_a_period_this_way(env):
    ws, cfg, store, put = env
    op = {"op": "away.read", "person": FULL, "source": "away", "entry": "a", "start": "2030-04-01", "gone": False}
    with pytest.raises(StoreError, match="absence"):
        apply_as_person(store, cfg, [op], "Noted who is away")
    assert not away_of(store, FULL)


def test_days_away_read_from_a_calendar_are_written_as_outside_content(env):
    ws, cfg, store, put = env
    put(calendar(vevent("a", f"{name(FULL)} vacation")))
    entries = [
        e for e in store.read().ledger(kind="person", record_id=FULL) if e.get("field") == "away" and e.get("changeset")
    ]
    # The calendar is outside content: what was read from it is never written as the person's own word.
    assert entries and {e["trust"] for e in entries} == {"untrusted"}
