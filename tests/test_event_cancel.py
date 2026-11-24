"""A later mail that cancels a booking already on the schedule marks that entry called off (S-0766; design 6.7, 6.32).

`event.cancel` is a data op with the cancelling words as evidence; the applier refuses it unless the entry was made
from a mail message by the assistant and nobody has changed it (the person's own entry, one a connected calendar
holds, a reminder and a repeating entry are never called off this way). Undo puts the entry back and records a
correction. Names, addresses and ids are made up."""

from __future__ import annotations

import json

import pytest

from engine import evaluate as ev
from engine.ai.adapters import stub
from engine.applier import Context, Inputs, apply_changeset, check
from engine.dispatcher import undo_changeset
from engine.names import People
from engine.ops import CHANGESET, OP_MODELS, TIERS
from engine.packet import _calendar_section
from engine.storage import WriteContext
from engine.tasks import TASKS
from tests import test_plain_calendar_entries as base
from tests.conftest import DEMO_A
from tests.test_knowledge_records import request as make_request
from tests.test_plain_calendar_entries import ME, NOW

cal = base.cal

_RUN = WriteContext("assistant", "untrusted", "event.add")
_PERSON = WriteContext("pm", "trusted", "test")
CONFIRM = "check in Friday, October 16 at 3:00 PM"
CANCEL = "Your reservation HS48213 for Friday, October 16 has been canceled"


HOTEL = "reservations@hotel.example.com"


def mail_from(store, sender, key):
    """A watched mail source with its snapshot, from `sender`; returns the source id."""
    with store.transaction() as tx:
        src = tx.create(
            "source",
            {
                "received_at": "2030-03-02T08:00:00+00:00",
                "sent_at": "2030-03-02T08:00:00+00:00",
                "kind": "watched:fake",
                "title": "Reservation update",
                "content_hash": "1" * 64,
                "trust": "untrusted",
                "watched": {"source": "inbox", "key": key, "change": "new", "by_you": False},
            },
            _RUN,
        )
        tx.create(
            "snapshot",
            {
                "source": "inbox",
                "key": key,
                "title": "Reservation update",
                "content_hash": "1" * 64,
                "seen_at": "2030-03-02T08:00:00+00:00",
                "message": {"sender": sender},
            },
            _RUN,
        )
        return src.id


def make_entry(store, *, source_kind="watched:fake", by_you=False, ctx=_RUN, sender=HOTEL, **entry):
    """A mail message and the entry made from it, written as `ctx`; returns the entry."""
    with store.transaction() as tx:
        if sender:
            tx.create(
                "snapshot",
                {
                    "source": "inbox",
                    "key": "m1",
                    "title": "Reservation confirmed",
                    "content_hash": "0" * 64,
                    "seen_at": "2030-03-01T08:00:00+00:00",
                    "message": {"sender": sender},
                },
                _RUN,
            )
        src = tx.create(
            "source",
            {
                "received_at": "2030-03-01T08:00:00+00:00",
                "sent_at": "2030-03-01T08:00:00+00:00" if source_kind.startswith("watched:") else None,
                "kind": source_kind,
                "title": "Reservation confirmed",
                "content_hash": "0" * 64,
                "trust": "untrusted",
                "watched": {"source": "inbox", "key": "m1", "change": "new", "by_you": by_you}
                if source_kind.startswith("watched:")
                else None,
            },
            _RUN,
        )
        data = {
            "title": "Hotel reservation HS48213",
            "start": "2030-03-07T15:00:00+00:00",
            "source": src.id,
            "trust": "untrusted",
            "evidence": {"source": src.id, "quote": CONFIRM},
            **entry,
        }
        return tx.create("event", data, ctx)


def _todo(store, **more):
    with store.transaction() as tx:
        return tx.create("action", {"text": "Pack for the hotel", "owners": [{"person": ME["id"]}], **more}, _PERSON)


def cancel_ops(store, cfg, entry_id, quote=CANCEL, sender=HOTEL, key="m2", raw=None):
    source = mail_from(store, sender, key) if sender else None
    op = {"op": "event.cancel", "id": entry_id, "evidence": {"quote": quote}}
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(
            make_request(store, "input", task="notes"), source, raw or quote, f"{quote}, as you asked.", "untrusted"
        ),
    )
    return cs, ctx


def refusals(store, cfg, entry_id):
    cs, ctx = cancel_ops(store, cfg, entry_id)
    return [p.message for p in check(cs, ctx) if p.severity == "refuse"]


def test_event_cancel_is_a_data_op_with_required_evidence_offered_to_notes_runs(cal):
    assert TIERS["event.cancel"] == "data" and "event.cancel" in TASKS["notes"].ops
    assert OP_MODELS["event.cancel"].model_fields["evidence"].is_required()


def test_a_mail_made_entry_is_called_off_with_the_words_kept_and_undo_puts_it_back(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    assert refusals(store, cfg, entry.id) == []
    cs, ctx = cancel_ops(store, cfg, entry.id)
    cs_id = apply_changeset(cs, [], ctx, run=None)
    done = store.read().get("event", entry.id).data
    assert done["cancelled"] is True and done["called_off_why"] == CANCEL
    assert [r["evidence"]["quote"] for r in store.read().changes_of(cs_id) if r["kind"] == "event"][0] == CANCEL
    assert "; called off)" in _calendar_section(store, cfg, NOW.date())
    undo_changeset(store, cs_id)
    back = store.read().get("event", entry.id).data
    assert not back["cancelled"] and back.get("called_off_why") is None


def test_undoing_a_call_off_the_assistant_made_is_a_correction_signal(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    cs, ctx = cancel_ops(store, cfg, entry.id)
    cs_id = apply_changeset(cs, [], ctx, run=None)
    before = [s.data["kind"] for s in store.read().list("signal")]
    undo_changeset(store, cs_id)
    after = [s.data["kind"] for s in store.read().list("signal")]
    assert after.count("undone") == before.count("undone") + 1


@pytest.mark.parametrize(
    ("why", "make"),
    [
        ("the person's own entry", lambda s: make_entry(s, ctx=_PERSON, trust="trusted")),
        ("typed in a note", lambda s: make_entry(s, source_kind="pasted")),
        ("mail the person wrote", lambda s: make_entry(s, by_you=True)),
        ("held by a calendar", lambda s: make_entry(s, key="uid-1:2030-03-07")),
        ("a reminder", lambda s: make_entry(s, reminder=_todo(s).id)),
        ("repeating", lambda s: make_entry(s, repeat={"every": "week"})),
        ("the person set a role", lambda s: make_entry(s, role="attend")),
        ("trusted", lambda s: make_entry(s, trust="trusted")),
    ],
)
def test_an_entry_that_did_not_come_from_mail_by_the_assistant_is_refused_and_left_alone(cal, why, make):
    ws, cfg, store, put = cal
    entry = make(store)
    problems = refusals(store, cfg, entry.id)
    assert problems, why
    cs, ctx = cancel_ops(store, cfg, entry.id)
    apply_changeset(cs, [], ctx, run=None)  # the change is refused, so nothing is written
    assert not store.read().get("event", entry.id).data["cancelled"]


def test_an_entry_the_person_changed_after_the_assistant_made_it_is_refused(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    with store.transaction() as tx:
        cur = tx.get("event", entry.id)
        tx.update("event", entry.id, {"start": "2030-03-08T15:00:00+00:00"}, _PERSON, read_version=cur.version)
    assert "the person has changed" in refusals(store, cfg, entry.id)[0]


def test_a_missing_or_already_called_off_entry_is_refused(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store, cancelled=True)
    assert "called off already" in refusals(store, cfg, entry.id)[0]
    assert "no calendar entry" in refusals(store, cfg, "EVT-999")[0]


def test_an_entry_called_off_holds_the_to_dos_tied_to_it_and_undo_releases_them(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    todo = _todo(store, due_event=entry.id)
    cs, ctx = cancel_ops(store, cfg, entry.id)
    cs_id = apply_changeset(cs, [], ctx, run=None)
    assert store.read().get("action", todo.id).data["on_hold"]["entry"] == entry.id
    undo_changeset(store, cs_id)
    assert not store.read().get("action", todo.id).data.get("on_hold")


def test_the_golden_cases_pass_on_their_scripted_answers_and_fails_an_answer_that_adds_or_leaves_it():
    only = [
        "booking-canceled-after-its-entry-was-made-calls-it-off",
        "booking-canceled-from-another-sender-is-held-not-called-off",
        "partial-cancellation-of-a-booking-asks-instead-of-calling-it-off",
    ]
    assert [r.passed for r in ev.evaluate(DEMO_A, stub=True, runs=1, only=only).results] == [True, True, True]


@pytest.fixture
def scripted(monkeypatch):
    def set_answer(ops):
        monkeypatch.setattr(
            ev, "set_responder", lambda r: stub.set_responder(None if r is None else (lambda task: json.dumps(ops)))
        )

    yield set_answer
    stub.set_responder(None)


@pytest.mark.parametrize(
    "ops",
    [
        [],
        [{"op": "event.add", "title": "Hotel", "start": "2030-03-07T15:00", "evidence": {"quote": CANCEL}}],
    ],
)
def test_the_golden_case_fails_when_the_entry_is_not_called_off(scripted, ops):
    scripted({"summary": "x", "ops": ops})
    only = ["booking-canceled-after-its-entry-was-made-calls-it-off"]
    assert not ev.evaluate(DEMO_A, stub=True, runs=1, only=only).results[0].passed


def test_the_schedule_and_the_agenda_carry_the_reason_of_a_called_off_entry(cal):
    from engine import schedule as schedule_module
    from engine import today
    from engine.today import zone

    ws, cfg, store, put = cal
    entry = make_entry(store)
    cs, ctx = cancel_ops(store, cfg, entry.id)
    apply_changeset(cs, [], ctx, run=None)
    day = NOW.astimezone(zone(cfg)).date().replace(year=2030, month=3, day=7)
    now = NOW.replace(year=2030, month=3, day=7, hour=9)
    agenda = [a for a in today.agenda(store, cfg, now) if a.snapshot == entry.id]
    assert [(a.cancelled, a.called_off_why) for a in agenda] == [(True, CANCEL)]
    shown = [e for d in schedule_module.schedule(store, cfg, now, day, 1) for e in [*d.all_day, *d.timed]]
    assert [(e.item.cancelled, e.item.called_off_why) for e in shown if e.item.snapshot == entry.id] == [(True, CANCEL)]


# ---- which mail may call an entry off (S-0767) ------------------------------------------------------------

OTHER = "desk@phish.example.net"


def run(store, cfg, entry_id, **more):
    cs, ctx = cancel_ops(store, cfg, entry_id, **more)
    cs_id = apply_changeset(cs, [], ctx, run=None)
    return cs_id, store.read().get("changeset", cs_id).data["ops"][0], store.read().get("event", entry_id).data


def test_same_domain_with_a_shared_reference_applies_at_once_even_from_another_address_of_that_domain(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    _, outcome, after = run(store, cfg, entry.id, sender="bookings@hotel.example.com")
    assert outcome["status"] == "applied" and after["cancelled"] is True


def test_a_different_domain_for_the_same_date_leaves_the_entry_and_asks(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    _, outcome, after = run(store, cfg, entry.id, sender=OTHER)
    assert outcome["status"] == "held" and not after["cancelled"] and not after.get("called_off_why")
    assert outcome["reason"] == (
        "A mail says your Hotel reservation HS48213 for Thu Mar 7 is canceled, "
        "but it's from a different sender: call it off?"
    )
    assert "; called off)" not in _calendar_section(store, cfg, NOW.date())


def test_yes_on_the_held_question_calls_it_off_and_no_leaves_it(cal):
    from engine import applier

    ws, cfg, store, put = cal
    first, second = make_entry(store), make_entry(store, title="Hotel reservation HS48213 (second)")
    yes, _, _ = run(store, cfg, first.id, sender=OTHER)
    no, _, _ = run(store, cfg, second.id, sender=OTHER, key="m3")
    applier.release(store, cfg, yes, 0)
    applier.decline_held(store, no, 0)
    assert store.read().get("event", first.id).data["cancelled"] is True
    assert not store.read().get("event", second.id).data["cancelled"]
    assert store.read().get("changeset", no).data["ops"][0]["reason"] == applier.DECLINED_REASON
    assert store.read().get("changeset", yes).data["ops"][0]["status"] == "applied"


def test_a_different_reference_changes_nothing_even_from_the_same_sender(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    quote = "Your reservation ZX99120 for Thursday, March 7 has been canceled"
    _, outcome, after = run(store, cfg, entry.id, quote=quote)
    assert outcome["status"] == "refused" and "different booking reference" in outcome["reason"]
    assert not after["cancelled"]


def test_no_reference_but_the_same_date_and_place_from_the_same_sender_applies(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store, title="Hotel stay", where="Harbor Stay Inn")
    quote = "Your stay at the harbor  stay inn on March 7 has been canceled"
    _, outcome, after = run(store, cfg, entry.id, quote=quote)
    assert outcome["status"] == "applied" and after["cancelled"] is True


def test_the_same_date_alone_asks_whether_or_not_the_entry_has_a_place(cal):
    ws, cfg, store, put = cal
    for where in (None, "Harbor Stay Inn"):
        entry = make_entry(store, title="Hotel stay", where=where)
        quote = "Your stay on March 7 has been canceled"
        _, outcome, after = run(store, cfg, entry.id, quote=quote)
        assert outcome["status"] == "held" and "doesn't say which booking" in outcome["reason"], where
        assert not after["cancelled"]


def test_the_same_sender_naming_neither_a_reference_nor_the_date_asks(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store, title="Hotel stay")
    _, outcome, after = run(store, cfg, entry.id, quote="Your stay has been canceled")
    assert outcome["status"] == "held" and "doesn't say which booking" in outcome["reason"] and not after["cancelled"]


def test_a_cancellation_whose_sender_cannot_be_told_asks(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    _, outcome, after = run(store, cfg, entry.id, sender=None)
    assert outcome["status"] == "held" and "doesn't show who sent it" in outcome["reason"] and not after["cancelled"]


def test_a_from_line_typed_in_the_text_never_counts_as_the_sender(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    raw = f"From: Harbor Stay <{HOTEL}>\nSubject: Canceled\n\n{CANCEL}"
    _, outcome, after = run(store, cfg, entry.id, sender=None, raw=raw)
    assert outcome["status"] == "held" and "doesn't show who sent it" in outcome["reason"] and not after["cancelled"]


def test_the_person_keeps_the_decision_when_a_note_of_theirs_confirms_the_call_off(cal):
    ws, cfg, store, put = cal
    entry = make_entry(store)
    cs, ctx = cancel_ops(store, cfg, entry.id, sender=OTHER)
    ctx.confirmed_by_pm = True
    assert not [p for p in check(cs, ctx) if p.severity in ("hold", "refuse")]


def test_an_entry_called_off_by_mail_is_a_today_line_worded_as_its_decision(cal):
    from engine import today_queue

    ws, cfg, store, put = cal
    entry = make_entry(store)
    run(store, cfg, entry.id)
    line = next(x for x in today_queue.queue(ws, store, cfg, NOW) if x.key == f"called_off:{entry.id}")
    assert (line.kind, line.state, line.group) == ("called_off", "mail", "decide")
    # the person's own call-off of an entry keeps its earlier line
    other = make_entry(store, title="Spa visit", source=None)
    with store.transaction() as tx:
        cur = tx.get("event", other.id)
        tx.update("event", other.id, {"cancelled": True}, _PERSON, read_version=cur.version)
    plain = next(x for x in today_queue.queue(ws, store, cfg, NOW) if x.key == f"called_off:{other.id}")
    assert plain.state != "mail"
