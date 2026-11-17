"""The tally of who the person deals with (S-0528, design 6.22): worked out from the headers of the mail the sources
already read, each way counted, the first and last day kept, machine-made senders kept apart, and a forgotten person
gone from it. The People step's suggestions read it. Addresses are generated, never real."""

from __future__ import annotations

from datetime import date

import pytest

from engine import contact_tally
from engine.people_forget import forget_person
from engine.storage import WriteContext
from tests.test_people_suggestions import fake_reads_mail, known_person, message, setup, who  # noqa: F401
from tests.test_source_intake import NOW

_W = WriteContext(actor="engine", trust="trusted", op="test.tally")


def dated(item: dict, day: date) -> dict:
    item["message"]["received"] = f"{day.isoformat()}T08:00:00+00:00"
    return item


def by_address(found) -> dict:
    return {c.address: c for c in found}


def test_two_reads_update_the_counts_each_way_and_the_days(tmp_path):
    first = [
        dated(message("m1", who(0)), date(2026, 9, 1)),
        dated(message("m2", who(0)), date(2026, 9, 5)),
    ]
    ws, cfg, store = setup(tmp_path, first, sent=False)
    after_one = by_address(contact_tally.tally(store, cfg))
    assert (after_one["c0@example.com"].from_them, after_one["c0@example.com"].to_them) == (2, 0)
    # A second read adds a message from them and one sent to them.
    from engine.watch import refresh

    cfg.watch.sources[0].settings["items"] = first + [
        dated(message("m4", who(0)), date(2026, 10, 2)),
        dated(message("m5", who(2)), date(2026, 10, 3)),
    ]
    refresh(ws, store, cfg, "m", NOW)
    found = by_address(contact_tally.tally(store, cfg))
    store.close()
    a = found["c0@example.com"]
    assert (a.from_them, a.to_them) == (3, 0)  # m1, m2 and m4 came from them
    assert (a.first, a.last) == (date(2026, 9, 1), date(2026, 10, 2))
    assert a.name == "Correspondent A" and a.shown == "Correspondent A"
    assert found["c2@example.com"].from_them == 1


def test_a_sent_source_counts_who_it_went_to_and_marks_that_the_person_wrote_to_them(tmp_path):
    items = [
        message("m1", "me@example.com", [who(0), who(1)]),
        message("m2", "me@example.com", [who(0)]),
    ]
    _ws, cfg, store = setup(tmp_path, items, sent=True)
    found = by_address(contact_tally.tally(store, cfg))
    store.close()
    assert (found["c0@example.com"].to_them, found["c0@example.com"].wrote_to) == (2, True)
    assert (found["c1@example.com"].to_them, found["c1@example.com"].from_them) == (1, 0)
    assert "me@example.com" not in found  # the person is not someone they deal with


def test_a_message_counts_an_address_once_however_often_the_header_names_it(tmp_path):
    items = [message("m1", "me@example.com", [who(0), who(0).upper(), who(0)])]
    _ws, cfg, store = setup(tmp_path, items, sent=True)
    found = by_address(contact_tally.tally(store, cfg))
    store.close()
    assert found["c0@example.com"].to_them == 1


def test_only_what_the_person_set_aside_is_kept_apart_and_every_other_mark_is_a_hint(tmp_path):
    """A recruiter at a role address, a tradesperson named like a company, a capitals name and a tagged address are all
    in the tally, not kept apart: a mark on an address is a fact for the assistant to weigh, never a verdict. Only a
    sender whose mail was set aside by the sorting or the person's own rule is kept apart."""
    items = [
        message("m1", who(0)),
        message("m2", who(1), bulk=True),
        message("m3", "No Reply <no-reply@example.com>"),
        message("m4", "Dana Ortiz <info@example.com>"),
        message("m5", "Pat Kin <sam.k+4f9a1c7e@example.com>"),
        message("m6", "Hale Support <help@example.com>"),
        message("m7", "PAT LEE <pat.lee@example.com>"),
    ]
    _ws, cfg, store = setup(tmp_path, items, sent=False)
    found = by_address(contact_tally.tally(store, cfg))
    store.close()
    assert {a for a, c in found.items() if c.apart is not None} == {"c1@example.com"}
    assert found["c0@example.com"].hints == ()
    assert found["c1@example.com"].hints == (contact_tally.BULK,)
    assert found["no-reply@example.com"].hints == (contact_tally.AUTOMATED,)
    assert found["info@example.com"].hints == (contact_tally.ROLE,)
    assert found["sam.k+4f9a1c7e@example.com"].hints == (contact_tally.CODE,)
    assert found["help@example.com"].hints == (contact_tally.COMPANY,)
    assert found["pat.lee@example.com"].hints == ()


def test_the_tally_is_ordered_by_messages_each_way_added_and_holds_no_message_text(tmp_path):
    items = [message(f"a{i}", who(0)) for i in range(3)] + [message("b", who(1))]
    _ws, cfg, store = setup(tmp_path, items, sent=False)
    found = contact_tally.tally(store, cfg)
    store.close()
    assert [c.address for c in found] == ["c0@example.com", "c1@example.com"]
    assert not any("Words about" in repr(c) or "Subject of" in repr(c) for c in found)


def test_forgetting_a_person_removes_their_row_from_both_directions(tmp_path):
    ws, cfg, store = setup(
        tmp_path,
        [message("in", who(0)), message("in2", who(1)), message("out", "me@example.com", [who(0), who(1)])],
        sent=False,
    )
    with store.transaction() as tx:
        owner = tx.create("person", {"full_name": "Correspondent A", "how_to_reach": {"email": ["c0@example.com"]}}, _W)
    before = by_address(contact_tally.tally(store, cfg))
    assert "c0@example.com" in before and "c1@example.com" in before
    held = store.read().get("person", owner.id)
    forget_person(ws, store, cfg, owner.id, read_version=held.version, summary="gone")
    after = by_address(contact_tally.tally(store, cfg))
    store.close()
    assert "c0@example.com" not in after
    assert "c1@example.com" in after  # someone else is untouched


def test_a_source_that_reads_no_mail_gives_an_empty_tally(tmp_path):
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    from engine.storage import Store

    store = Store(ws.db_path)
    try:
        assert contact_tally.tally(store, cfg) == []
    finally:
        store.close()


@pytest.mark.parametrize("bad", ["", "not an address", "<>", "Name <>"])
def test_a_header_with_no_address_is_left_out(tmp_path, bad):
    _ws, cfg, store = setup(tmp_path, [message("m1", who(0)), message("m2", bad)], sent=False)
    found = contact_tally.tally(store, cfg)
    store.close()
    assert [c.address for c in found] == ["c0@example.com"]
