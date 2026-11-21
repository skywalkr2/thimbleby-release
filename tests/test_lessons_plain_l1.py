"""What Reginald learned reads right and goes the right way (S-0580, S-0581): a correction's lesson rests on the
person's words or the message's, never on the app's own reason; a value from one item is never a lesson; a note the
person typed is theirs; near-identical proposals are one. Names and ids come from the fixtures; the AI is the stub."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from engine import knowledge, learn, proposals, set_aside
from engine import packet as packets
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.dispatcher import process, signal
from engine.intake import hand_in
from engine.ops import LessonAddOp
from engine.records import Scope
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
_TEST = WriteContext(actor="pm", trust="trusted", op="test.l1")
PROJECT = fixture_records(DEMO_B, "project")[0]
ALERT = "From: Site Alerts <alerts@example.com>\n\n12 pages now return an error when a search service visits them."
REASON = "your mail service files it under updates"
TRACKING = "Parcel tracking number: 9400111899223197428490"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path)
    yield ws, cfg, store
    store.close()
    set_responder(None)


def answers(*bodies: dict) -> list:
    asked: list = []
    queue = [json.dumps(b) for b in bodies]

    def responder(task):
        asked.append(task)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    set_responder(responder)
    return asked


def lesson(text: str, quote: str | None = None, **more) -> dict:
    op = {"op": "lesson.add", "text": text, "guard": "Make a to-do of each.", **more}
    if quote:
        op["evidence"] = {"quote": quote}
    return {"summary": "A lesson.", "topic": "website alerts", "ops": [op]}


def corrected(env, note: str) -> tuple[str, str]:
    """An alert handed in and read, then the person's correction with this note. Returns the learning request."""
    ws, cfg, store = env
    handed = hand_in(ws, store, pasted=ALERT, now=NOW)
    answers({"summary": "Noted.", "ops": []})
    process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    signal(store, "pulled_back", [handed.request], note, now=NOW)
    (queued,) = [r for r in store.read().list("request") if r.data["task"] == learn.TASK]
    return queued.id, handed.request


# ---- S-0580: a correction's lesson is the correction's way round, and rests on no app wording -----------------------


def test_the_note_of_bringing_a_message_in_says_what_the_person_did_and_never_why_it_was_set_aside(env):
    _, _, store = env
    view = store.read()
    side = PROJECT["id"]
    assert set_aside.bring_in_note(view, personal=False, project=side) == (
        f"The person marked this message as work for {PROJECT['name']}."
    )
    assert set_aside.bring_in_note(view, personal=False) == "The person marked this message as work."
    assert set_aside.bring_in_note(view, personal=True) == "The person marked this message as personal."


def test_the_packet_of_a_message_brought_in_says_the_direction_and_marks_the_app_note_as_no_source(env):
    ws, cfg, store = env
    queued, _ = corrected(env, set_aside.bring_in_note(store.read(), personal=False, project=PROJECT["id"]))
    request = packets.build(ws, store, cfg, queued, NOW.date()).task.request
    assert f"The person marked this message as work for {PROJECT['name']}." in request
    assert "never a source to quote" in request
    assert "teach that this kind of item is work" in request and "never the reverse" in request
    assert "<untrusted" in request and "12 pages now return an error" in request, "the message is outside content"


def test_a_lesson_whose_evidence_is_the_apps_own_reason_is_refused_and_one_quoting_the_message_is_taken(env):
    ws, cfg, store = env
    queued, _ = corrected(env, f"Set aside: {REASON}")  # a correction recorded before the note stated the act
    wrong = lesson("Automated notices that the mail service files under updates need no note.", REASON)
    right = lesson(
        "Alerts like this about the website are work for this project, so make each one a to-do.",
        "12 pages now return an error",
    )
    asked = answers(wrong, right)
    process(ws, store, cfg, Router(cfg, store, env={}), queued, now=NOW)
    assert len(asked) == 2, "the first answer was sent back"
    assert "the app's own wording" in asked[1].request
    (made,) = store.read().list("lesson")
    assert made.data["evidence"]["quote"] == "12 pages now return an error"
    # It only describes, and it restates the person's own correction, so it is in use at once.
    assert (made.data["status"], made.data["activated"], made.data["kept_by"]) == ("active", "correction", None)


def test_the_apps_words_are_its_note_for_a_pulled_back_correction_and_its_reason_on_the_records_it_names(env):
    _, _, store = env
    with store.transaction() as tx:
        shelved = tx.create(
            "request",
            {
                "task": "notes",
                "origin": "input",
                "state": "done",
                "created_at": NOW.isoformat(),
                "waiting": f"Set aside: {REASON}",
            },
            _TEST,
        ).id
    signal(store, "pulled_back", [shelved], "The person marked this message as work.", now=NOW)
    (made,) = store.read().list("signal")
    said = learn.app_words(store.read(), made.data)
    assert "The person marked this message as work." in said and REASON in said
    own = signal(store, "sent_back", [shelved], "These alerts are my work.", now=NOW)
    assert learn.app_words(store.read(), store.read().get("signal", own).data)[0] == REASON, "their note is theirs"


# ---- S-0581 (1): a value from one item is never a lesson and never offered -------------------------------------------


def test_a_value_from_one_item_is_not_a_lesson_while_dates_and_plain_words_are():
    assert proposals.single_value(TRACKING)
    assert proposals.single_value("Order 1Z999AA10123456784 shipped")
    assert not proposals.single_value("Mail due 2026-11-16 goes to the printer by the 16th.")
    assert not proposals.single_value("Alerts like this about the website are work for this project.")


def test_a_lesson_that_is_a_tracking_number_is_sent_back_and_one_already_waiting_is_never_offered(env):
    ws, cfg, store = env
    handed = hand_in(ws, store, pasted=ALERT, now=NOW)
    answers({"summary": "Noted.", "ops": []})
    process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    signal(store, "sent_back", [handed.request], "Keep the parcel details.", now=NOW)
    (queued,) = [r for r in store.read().list("request") if r.data["task"] == learn.TASK]
    asked = answers(lesson(TRACKING, "12 pages now return an error"), {"summary": "x", "topic": "x", "ops": []})
    process(ws, store, cfg, Router(cfg, store, env={}), queued.id, now=NOW)
    assert store.read().list("lesson") == [] and len(asked) >= 2
    assert "not a lesson" in asked[1].request
    # One that is already waiting (made before this rule) is not offered.
    with store.transaction() as tx:
        tx.create(
            "lesson",
            {
                "text": TRACKING,
                "origin": "input",
                "trust": "untrusted",
                "status": "proposed",
                "learned_at": NOW.isoformat(),
                "applies_to": {},
            },
            _TEST,
        )
    assert proposals.proposals(store.read()) == []


# ---- S-0581 (2): a note the person typed is theirs and offered for Keep ----------------------------------------------


def term(quote: str) -> dict:
    return {
        "summary": "A term from the note.",
        "topic": "website alerts",
        "ops": [
            {
                "op": "glossary.add",
                "text": "Website alert: work, so make each one a to-do for a fix.",
                "term": "Website alert",
                "meaning": "work, so make each one a to-do for a fix",
                "evidence": {"quote": quote},
            }
        ],
    }


def test_a_note_the_person_typed_beside_outside_content_is_marked_theirs_and_offered_for_keep(env):
    ws, cfg, store = env
    note = "Any email coming in about the website should be created as to-dos for fixes."
    handed = hand_in(ws, store, note=note, pasted=ALERT, now=NOW)
    answers(term("should be created as to-dos for fixes"))
    process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    (made,) = store.read().list("glossary_entry")
    assert (made.data["origin"], made.data["trust"], made.data["status"]) == ("person", "trusted", "active")
    assert made.data["activated"] == "person_note", "the person's own typed words apply at once, with no Keep"
    assert proposals.proposals(store.read()) == [] and proposals.tentative(store.read()) == []


def test_the_same_words_quoted_from_the_outside_content_stay_outside(env):
    ws, cfg, store = env
    handed = hand_in(ws, store, note="Look at this.", pasted=ALERT, now=NOW)
    answers(term("12 pages now return an error"))
    process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    (made,) = store.read().list("glossary_entry")
    assert (made.data["origin"], made.data["trust"]) == ("input", "untrusted")


# ---- S-0581 (5): near-identical proposals are one --------------------------------------------------------------------


def test_two_near_identical_proposals_are_one_card_and_a_third_that_differs_is_another(env):
    _, _, store = env
    standing = knowledge.Standing(False, None, "input", "untrusted", None, None, NOW.isoformat(), alike=1.0)
    scope = Scope(scope="projects", projects=[PROJECT["id"]])
    texts = [
        "Website alerts about pages returning errors must be work: make each one a to-do for a fix.",
        "Website alerts about pages returning errors must be work: make each one a to-do.",
        "Questions about the printer go to the production lead.",
    ]
    with store.transaction() as tx:
        for text in texts:
            knowledge.apply(tx, LessonAddOp(text=text, applies_to=scope), _TEST, standing)
    view = store.read()
    assert len(view.list("lesson")) == 3
    one = proposals.proposals(view, alike=0.8)
    assert [p.stored.data["text"] for p in one] == [texts[0], texts[2]]
    assert len(proposals.proposals(view)) == 3, "exactly the same words are the only ones joined without a threshold"
    narrow = knowledge.Standing(False, None, "input", "untrusted", None, None, NOW.isoformat(), alike=0.8)
    with store.transaction() as tx:
        merged = knowledge.apply(tx, LessonAddOp(text=texts[1], applies_to=scope), _TEST, narrow)
    assert merged[0]["id"] == view.list("lesson")[0].id, "a near-identical one merges when it is made"
