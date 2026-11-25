# ruff: noqa: F811
"""An answer is being read until its run has judged it, and waits in the list when that run can't go (design 6.8;
S-0813). Names and ids come from the fixtures."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from engine.answer_state import answer_states
from engine.intake import note_as_input
from engine.open_items import open_questions
from engine.storage import Store, WriteContext
from engine.worker import release_paused
from tests.test_setup import client
from tests.test_silent_stops import (
    Scripted,
    data,
    env,  # noqa: F401  (the engine fixture)
    set_responder,
    worker_of,
)

_PERSON = WriteContext(actor="pm", trust="trusted", op="test.answer_state")
EITHER = "Matte or soft-touch for the jacket?"


def ask(store, cfg) -> str:
    with store.transaction() as tx:
        return tx.create("question", {"to": cfg.workspace.user.person, "title": EITHER}, _PERSON).id


def answer(env, qid, text="Soft-touch") -> str:
    """The person answers as the Answer route does: the words are stored and go in as a note about the question."""
    ws, cfg, store, clock = env
    with store.transaction() as tx:
        cur = tx.get("question", qid)
        tx.update("question", qid, {"status": "answered", "answer": text}, _PERSON, read_version=cur.version)
    return note_as_input(ws, store, cfg, item=("question", qid), text=text, route="answered", now=clock())


def row(env, qid):
    _, cfg, store, clock = env
    found = [q for q in open_questions(store, cfg, clock().date(), clock()) if q.id == qid]
    return found[0] if found else None


def settle(qid) -> str:
    return json.dumps(
        {
            "summary": "Noted the finish.",
            "ops": [{"op": "question.done", "id": qid, "answer": "Soft-touch", "evidence": {"quote": "Soft-touch"}}],
        }
    )


def reword(qid) -> str:
    return json.dumps(
        {
            "summary": "Asked which finish.",
            "ops": [{"op": "question.update", "id": qid, "title": "Which finish?", "text": "Pick one."}],
        }
    )


def test_an_answered_question_stays_in_its_list_as_being_read_until_its_run_is_done(env):
    _, cfg, store, _ = env
    qid = ask(store, cfg)
    request = answer(env, qid)
    assert row(env, qid).state == "reading" and row(env, qid).answer_why is None
    assert answer_states(store.read())[qid].request == request
    set_responder(Scripted(settle(qid)))
    worker_of(env).run_pending()
    assert row(env, qid) is None  # judged: it leaves


def test_an_unclear_answer_comes_back_open_and_reworded_not_as_being_read(env):
    _, cfg, store, _ = env
    qid = ask(store, cfg)
    answer(env, qid, "Yes please")
    set_responder(Scripted(reword(qid)))
    worker_of(env).run_pending()
    found = row(env, qid)
    assert found.state == "yours" and found.title == "Which finish?"


@pytest.mark.parametrize("stop", ["needs_you", "failed"])
def test_an_answer_whose_run_stopped_waits_to_be_read_with_its_reason(env, stop):
    _, cfg, store, _ = env
    qid = ask(store, cfg)
    request = answer(env, qid)
    with store.transaction() as tx:
        cur = tx.get("request", request)
        tx.update(
            "request", request, {"state": stop, "waiting": "Waiting for your go"}, _PERSON, read_version=cur.version
        )
    found = row(env, qid)
    assert (found.state, found.answer_why) == ("answer_waiting", "Waiting for your go")


def test_a_timed_wait_that_has_ended_is_being_read_again(env):
    _, cfg, store, clock = env
    qid = ask(store, cfg)
    request = answer(env, qid)
    until = clock() + timedelta(hours=2)
    with store.transaction() as tx:
        cur = tx.get("request", request)
        cause = {"kind": "paused", "account": "x/y", "until": until.isoformat()}
        tx.update(
            "request", request, {"cause": cause, "waiting": "Paused until later"}, _PERSON, read_version=cur.version
        )
    assert row(env, qid).state == "answer_waiting"
    clock.at = clock() + timedelta(hours=3)
    assert row(env, qid).state == "reading"


def test_the_persons_path_no_account_waits_to_be_read_then_an_account_reads_it_and_it_leaves(env):
    _, cfg, store, _ = env
    given = cfg.ai.tiers["routine"].model_copy()
    cfg.ai.tiers["routine"].use = ""
    cfg.ai.tiers["routine"].fallback = []
    qid = ask(store, cfg)
    request = answer(env, qid)
    assert row(env, qid).state == "reading"
    set_responder(Scripted(settle(qid)))
    worker_of(env).run_pending()
    assert data(env, request)["cause"]["kind"] == "no_account"
    waiting = row(env, qid)
    assert waiting.state == "answer_waiting" and "account" in waiting.answer_why.lower()
    cfg.ai.tiers["routine"].use, cfg.ai.tiers["routine"].fallback = given.use, given.fallback
    assert release_paused(store) == 1
    assert row(env, qid).state == "reading"
    worker_of(env).run_pending()
    assert row(env, qid) is None


def test_changing_an_answer_nobody_has_read_takes_the_earlier_one_back(env):
    ws, cfg, store, _ = env
    qid = ask(store, cfg)
    first = answer(env, qid, "Matte")
    c, api = client(ws, cfg, store)
    got = c.post(f"{api}/questions/{qid}/answer", json={"text": "Soft-touch"})
    assert got.status_code == 200, got.text
    second = got.json()["request"]
    fresh = Store(ws.db_path, cfg=cfg)
    try:
        assert fresh.read().get("request", first).data["state"] == "done"
        assert fresh.read().get("request", second).data["state"] == "queued"
        assert answer_states(fresh.read())[qid].request == second
    finally:
        fresh.close()
