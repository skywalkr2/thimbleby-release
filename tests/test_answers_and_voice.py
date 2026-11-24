"""An answer is judged by the run before it stands, a refused day keeps what the op said, a reworded question asked
before is caught, every summary is in one voice (design 6.8, 6.22;
S-0717, S-0718, S-0720, S-0730). Names and ids come from the fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from engine import answer_effect
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.applier import Context, Inputs, check
from engine.dispatcher import process
from engine.intake import hand_in, note_as_input
from engine.lists import ensure as ensure_lists
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

_PERSON = WriteContext(actor="pm", trust="trusted", op="test.answers_and_voice")
NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
EITHER = "Matte or soft-touch for the jacket?"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    ensure_lists(store)
    yield ws, cfg, store
    store.close()
    set_responder(None)


def run(env, request_id, answer: dict):
    ws, cfg, store = env
    set_responder(lambda task: json.dumps(answer))
    return process(ws, store, cfg, Router(cfg, store, env={}), request_id, now=NOW)


def ask(store, cfg, title=EITHER, **more) -> str:
    with store.transaction() as tx:
        return tx.create("question", {"to": cfg.workspace.user.person, "title": title, **more}, _PERSON).id


def answer(ws, store, cfg, qid, text, route="answered") -> str:
    """The person answers as the Answer route does: the words are stored and go in as a note about the question."""
    with store.transaction() as tx:
        cur = tx.get("question", qid)
        tx.update("question", qid, {"status": "answered", "answer": text}, _PERSON, read_version=cur.version)
    return note_as_input(ws, store, cfg, item=("question", qid), text=text, route=route, now=NOW)


# ---- S-0717: an unclear answer is not the answer ---------------------------------------------------------------------


def reword(qid, title="Which finish for the jacket: matte or soft-touch?"):
    return {
        "summary": "Asked which finish you want, since the answer didn't pick one.",
        "ops": [{"op": "question.update", "id": qid, "title": title, "text": "Pick one: matte or soft-touch."}],
    }


def test_an_unclear_answer_leaves_the_question_open_reworded_and_stores_no_answer(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    request = answer(ws, store, cfg, qid, "Yes please")
    before = len(store.read().list("question"))
    run(env, request, reword(qid))
    found = store.read().get("question", qid).data
    assert found["status"] == "open" and found["answer"] is None
    assert found["title"].startswith("Which finish")
    assert len(store.read().list("question")) == before  # reworded, not asked a second time


def settle(qid, words="Soft-touch"):
    return {
        "summary": "Noted the finish.",
        "ops": [
            {
                "op": "question.done",
                "id": qid,
                "answer": f"{words} for the jacket",
                "evidence": {"quote": words},
            }
        ],
    }


def test_a_clear_answer_stays_the_answer(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    request = answer(ws, store, cfg, qid, "Soft-touch")
    run(env, request, settle(qid))
    found = store.read().get("question", qid).data
    assert found["status"] == "answered" and found["answer"] == "Soft-touch for the jacket"


def test_a_run_that_neither_closes_nor_rewords_gives_the_answer_back(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    request = answer(ws, store, cfg, qid, "Yes please")
    other = {"op": "question.add", "title": "Which finish do you want for the jacket?", "to": cfg.workspace.user.person}
    run(env, request, {"summary": "Asked which finish.", "ops": [other]})
    found = store.read().get("question", qid).data
    assert found["status"] == "open" and found["answer"] is None


def test_a_run_that_does_nothing_with_the_answer_gives_it_back_after_the_return_round(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    request = answer(ws, store, cfg, qid, "Yes please")
    run(env, request, {"summary": "Nothing.", "ops": []})
    assert store.read().get("question", qid).data["status"] == "answered"  # sent back once, still being judged
    redone = store.read().get("request", request).data["superseded_by"]
    run(env, redone, {"summary": "Nothing.", "ops": []})
    found = store.read().get("question", qid).data
    assert found["status"] == "open" and found["answer"] is None


def test_closing_an_answered_question_is_refused_when_the_run_is_not_judging_its_answer(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    answer(ws, store, cfg, qid, "Soft-touch")
    unrelated = hand_in(ws, store, note="", pasted="Soft-touch it is.", now=NOW).request
    cs = CHANGESET.validate_python({"ops": [settle(qid)["ops"][0]]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        ("question.done",),
        Inputs(unrelated, None, "", "Soft-touch", "untrusted"),
        actor="assistant",
    )
    assert "targets" in [p.check for p in check(cs, ctx) if p.severity == "refuse"]


def test_a_question_done_whose_quote_is_not_in_the_input_is_refused(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    request = answer(ws, store, cfg, qid, "Soft-touch")
    run(env, request, settle(qid, "Matte, definitely"))  # words the person never wrote
    ops = [o for c in store.read().list("changeset") for o in c.data["ops"] if o["op"].get("op") == "question.done"]
    assert ops and all(o["status"] != "applied" for o in ops)
    assert store.read().get("question", qid).data["answer"] == "Soft-touch"  # never the made-up words


def test_a_reword_is_refused_unless_the_run_is_judging_that_questions_answer(env):
    ws, cfg, store = env
    qid, other = ask(store, cfg), ask(store, cfg, "Which day suits the handover?")
    answered = answer(ws, store, cfg, qid, "Yes please")
    assert answer_effect.judging_answer(store.read(), answered, qid)
    assert not answer_effect.judging_answer(store.read(), answered, other)  # another question
    unrelated = hand_in(ws, store, note="", pasted="Unrelated text.", now=NOW).request
    assert not answer_effect.judging_answer(store.read(), unrelated, qid)  # not an answer's run
    op = reword(qid)["ops"][0]
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        ("question.update",),
        Inputs(unrelated, None, "", "", "untrusted"),
        actor="assistant",
    )
    assert [p.check for p in check(cs, ctx) if p.severity == "refuse"] == ["person-only"]


def test_the_assistants_reword_is_not_counted_as_the_persons_correction(env):
    ws, cfg, store = env
    qid = ask(store, cfg)
    run(env, answer(ws, store, cfg, qid, "Yes please"), reword(qid))
    assert not [s for s in store.read().list("signal") if s.data.get("kind") == "reworded"]


# ---- S-0718: a day the quote doesn't state is left out, not the whole fact -------------------------------------------


def test_a_fact_whose_day_the_quote_does_not_state_is_kept_without_the_day(env):
    ws, cfg, store = env
    words = "The marketing group needs the jacket copy before then"
    request = hand_in(ws, store, note="", pasted=f"Thread of 20 November.\n\n{words}.", now=NOW).request
    fact = {
        "op": "fact",
        "text": "The marketing group needs the jacket copy by December 3",
        "on": "2026-12-03",
        "on_kind": "deadline",
        "evidence": {"quote": words},
    }
    run(env, request, {"summary": "Recorded what marketing needs.", "ops": [fact]})
    kept = [f for f in store.read().list("fact") if "jacket copy" in f.data["text"]]
    assert kept and kept[0].data.get("on") is None and kept[0].data.get("on_kind") is None


def test_a_fact_whose_day_the_quote_states_keeps_it(env):
    ws, cfg, store = env
    words = "Marketing needs the jacket copy by December 3, 2026"
    request = hand_in(ws, store, note="", pasted=f"{words}.", now=NOW).request
    fact = {
        "op": "fact",
        "text": "Marketing needs the jacket copy by December 3, 2026",
        "on": "2026-12-03",
        "on_kind": "deadline",
        "evidence": {"quote": words},
    }
    run(env, request, {"summary": "Recorded the deadline.", "ops": [fact]})
    kept = [f for f in store.read().list("fact") if "jacket copy" in f.data["text"]]
    assert kept and str(kept[0].data["on"]) == "2026-12-03"


# ---- S-0720: a reworded question asked before ------------------------------------------------------------------------


def problems(env, title, name, text="", to=None):
    _, cfg, store = env
    op = {
        "op": "question.add",
        "to": to or cfg.workspace.user.person,
        "title": title,
        "text": text,
        "would_change": {"what": "setting", "setting": "ui.today.stale_after_days"},
    }
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store, cfg, People(store, cfg), ("question.add",), Inputs("REQ-1", None, "", "", "trusted"), actor="assistant"
    )
    return [p for p in check(cs, ctx) if p.check == name]


def close(store, qid, status, **more):
    with store.transaction() as tx:
        cur = tx.get("question", qid)
        tx.update("question", qid, {"status": status, **more}, _PERSON, read_version=cur.version)


def test_a_reworded_question_after_a_drop_is_returned_with_the_reason(env):
    _, cfg, store = env
    qid = ask(store, cfg, "Which printer takes the hardcover run of T-12?", text="Ticket T-12 needs a printer.")
    close(store, qid, "dropped", dropped_reason="Settled on a call")
    (found,) = problems(env, "Which printer should take the T-12 hardcover run now?", "question-reworded-before")
    assert found.severity == "return" and qid in found.message and "Settled on a call" in found.message


def test_a_reworded_question_after_an_old_answer_is_returned_with_the_answer(env):
    _, cfg, store = env
    store.clock = lambda: "2026-01-01T09:00:00+00:00"
    qid = ask(store, cfg, "Which printer takes the hardcover run?")
    close(store, qid, "answered", answer="The usual one.")
    store.clock = lambda: "2027-06-01T09:00:00+00:00"
    (found,) = problems(env, "Hardcover run: which printer will take it?", "question-reworded-before")
    assert "The usual one." in found.message


def test_a_different_question_or_a_different_person_is_not_returned(env):
    _, cfg, store = env
    qid = ask(store, cfg, "Which printer takes the hardcover run?")
    close(store, qid, "dropped", dropped_reason="Settled")
    assert not problems(env, "When do the jacket proofs arrive?", "question-reworded-before")


def test_the_packet_lists_the_closed_questions_with_their_answers(env):
    from engine.packet import _closed_questions

    ws, cfg, store = env
    qid = ask(store, cfg, "Which printer takes the hardcover run?")
    close(store, qid, "answered", answer="The usual one.")
    gone = ask(store, cfg, "Is the vendor visit still on?")
    close(store, gone, "dropped", dropped_reason="Not needed")
    open_one = ask(store, cfg, "Which day suits the handover?")
    section = _closed_questions(store, People(store, cfg), None, 15)
    assert qid in section and "The usual one." in section and "Not needed" in section and open_one not in section
    assert _closed_questions(store, People(store, cfg), None, 0) == ""


# ---- S-0730: one voice -----------------------------------------------------------------------------------------------


def voiced(env, summary):
    _, cfg, store = env
    cs = CHANGESET.validate_python({"summary": summary, "ops": []}, context={"op_models": store.plugins.ops})
    ctx = Context(store, cfg, People(store, cfg), (), Inputs("REQ-1", None, "", "", "trusted"), actor="assistant")
    return [p for p in check(cs, ctx) if p.check == "summary-first-person"]


@pytest.mark.parametrize(
    "summary",
    ["You asked me to move the review.", "I can't draft that.", "I'll look at it.", "Moved it; that's my reading."],
)
def test_a_summary_in_the_first_person_is_returned(env, summary):
    (found,) = voiced(env, summary)
    assert found.severity == "return" and "you" in found.guidance.lower()


@pytest.mark.parametrize(
    "summary",
    ["Put two of the actions on hold.", 'Recorded that Ana said "I will send it Friday".', "Asked you which finish."],
)
def test_a_summary_in_past_tense_about_the_work_passes(env, summary):
    assert not voiced(env, summary)


# ---- the golden-set cases of these stories ---------------------------------------------------------------------------

CASES = [
    "unclear-answer-rewords-the-question",
    "refused-day-keeps-what-the-note-said",
    "note-settling-a-hold-closes-the-plans-questions",
    "note-settling-one-part-leaves-the-other-parts-questions-open",
    "message-request-with-no-mail-account-is-never-refused",
    "own-note-drafting-a-message-is-a-copy-draft-not-a-todo",
]


def test_the_golden_set_cases_of_these_stories_pass_on_their_scripted_answers():
    from pathlib import Path

    from engine import evaluate

    demo = Path(__file__).resolve().parent.parent / "workspaces" / "demo-a"
    report = evaluate.evaluate(demo, stub=True, runs=1, only=CASES)
    assert sorted(r.case for r in report.results) == sorted(CASES)
    assert all(r.passed for r in report.results), [(r.case, r.missing, r.forbidden) for r in report.results]


# ---- S-0731: a message is drafted from the person's own words, never from outside text -------------------------------


def draft_op(store, cfg):
    who = next(p.id for p in store.read().list("person") if p.id != cfg.workspace.user.person)
    return {
        "op": "act.draft",
        "channel": "copy",
        "target": {"kind": "message", "action": "send", "recipients": [{"person": who}]},
        "parts": {"subject": "Jacket copy", "body": "When can we have the jacket copy?"},
    }


def refusals(env, request_id, trust, op=None):
    ws, cfg, store = env
    cs = CHANGESET.validate_python({"ops": [op or draft_op(store, cfg)]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        ("act.draft",),
        Inputs(request_id, None, "", "", trust),
        actor="assistant",
    )
    return [p.check for p in check(cs, ctx) if p.severity == "refuse"]


def test_notes_and_asks_are_offered_the_draft_op_and_no_other_outward_act():
    from engine.ops import ACT_OPS
    from engine.tasks import task_kind

    for name in ("notes", "ask"):
        assert set(task_kind(name).ops) & ACT_OPS == {"act.draft"}


def test_the_persons_own_note_may_draft_a_message(env):
    ws, cfg, store = env
    request = hand_in(ws, store, note="Draft a short message asking about the jacket copy", now=NOW).request
    assert refusals(env, request, "trusted") == []


def test_an_outside_mail_asking_for_a_message_drafts_nothing(env):
    ws, cfg, store = env
    mail = "Please send Ana a message saying the jacket copy is late."
    request = hand_in(ws, store, note="", pasted=mail, now=NOW).request
    assert refusals(env, request, "untrusted") == ["act-from-outside"]
    # Not the person's words even when the input is marked trusted: a request made by something else.
    with store.transaction() as tx:
        other = tx.create(
            "request",
            {"task": "notes", "origin": "schedule", "state": "queued", "note": mail, "created_at": store.clock()},
            _PERSON,
        ).id
    assert refusals(env, other, "trusted") == ["act-from-outside"]
    # Run end to end: the draft is refused and no act exists.
    run(env, request, {"summary": "Drafted the message.", "ops": [draft_op(store, cfg)]})
    assert store.read().list("act") == []
