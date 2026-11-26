"""A good answer is never sent back: one that is would be a false return, costing a model call each time. Each golden
case with a real model's known-good answer is run through the app's whole pipeline
with that answer; no request may carry a return round. A file holding several rounds counts its last as the good one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from engine import evaluate as ev
from engine.ai.adapters import stub
from tests.conftest import DEMO_A, DEMO_B
from tests.test_own_note_holds import env  # noqa: F401  (the workspace the hold test runs in)

#: What every return round's request starts its part about the previous answer with (`engine/dispatcher.py`).
RETURNED = "Your previous answer"

CASES = sorted(p for demo in (DEMO_A, DEMO_B) for p in (demo / "evals" / "real-answers").glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_a_known_good_answer_goes_through_every_check_with_no_return_round(path: Path, monkeypatch):
    found = json.loads(path.read_text(encoding="utf-8"))
    good = json.dumps(found[-1] if isinstance(found, list) else found)
    returned: list[str] = []

    def answer(task):
        if RETURNED in task.request:
            returned.append(task.request[task.request.index(RETURNED) :][-1500:])
        return good

    monkeypatch.setattr(ev, "set_responder", lambda r: stub.set_responder(None if r is None else answer))
    report = ev.evaluate(path.parent.parent.parent, stub=True, runs=1, only=[path.stem])
    assert report.results, path.stem
    assert not returned, (path.stem, returned[0])


def test_a_hold_answered_by_closing_the_plans_questions_alone_is_never_sent_back(monkeypatch):
    """The person's own "hold X until Y" answered with no to-do but with what it settles (the plan's questions closed)
    is a good answer: only an answer of notes and facts alone goes back to be asked about the held work."""
    case = "own-note-settling-a-hold-closes-the-plans-questions"
    stub_answer = yaml.safe_load((DEMO_A / "evals" / f"{case}.yaml").read_text(encoding="utf-8"))["stub_answer"]
    assert {op["op"] for op in stub_answer["ops"]} == {"question.done"}
    returned: list[str] = []

    def answer(task):
        if RETURNED in task.request:
            returned.append(task.request[task.request.index(RETURNED) :][-1500:])
        return json.dumps(stub_answer)

    monkeypatch.setattr(ev, "set_responder", lambda r: stub.set_responder(None if r is None else answer))
    report = ev.evaluate(DEMO_A, stub=True, runs=1, only=[case])
    assert report.results and report.results[0].passed, report.results
    assert not returned, returned[0]


def test_a_choice_still_open_answered_with_a_decision_question_is_never_sent_back(monkeypatch):
    """The person's own "I haven't decided ..." answered with a decision question is a good answer: only an answer of
    notes and facts alone goes back to be asked whether it is a decision for the person."""
    case = "own-note-undecided-choice-is-a-decision-question"
    stub_answer = yaml.safe_load((DEMO_B / "evals" / f"{case}.yaml").read_text(encoding="utf-8"))["stub_answer"]
    assert {op["op"] for op in stub_answer["ops"]} == {"question.add"}
    returned: list[str] = []

    def answer(task):
        if RETURNED in task.request:
            returned.append(task.request[task.request.index(RETURNED) :][-1500:])
        return json.dumps(stub_answer)

    monkeypatch.setattr(ev, "set_responder", lambda r: stub.set_responder(None if r is None else answer))
    report = ev.evaluate(DEMO_B, stub=True, runs=1, only=[case])
    assert report.results and report.results[0].passed, report.results
    assert not returned, returned[0]


def test_a_hold_of_a_meeting_answered_by_doing_something_with_it_is_never_sent_back(env):  # noqa: F811
    """ "Hold the meeting until Friday" answered with the to-do on hold (any op that is not a note or a fact) is a good
    answer: the net for a hold only catches an answer of notes and facts alone."""
    from tests.test_own_note_holds import (
        test_a_hold_of_a_meeting_that_does_something_with_it_is_never_sent_back as case,
    )

    case(env)


def _run_with(case: str, answer: dict, monkeypatch):
    monkeypatch.setattr(
        ev, "set_responder", lambda r: stub.set_responder(None if r is None else lambda task: json.dumps(answer))
    )
    return ev.evaluate(DEMO_B, stub=True, runs=1, only=[case])


def test_a_promise_kept_only_as_a_fact_fails_its_golden_case(monkeypatch):
    """The meeting note's promise recorded as a fact alone (the cheap model's slip) is not a pass, so a prompt change
    that brings it back shows."""
    case = "own-note-meeting-promise-is-the-promisers-to-do"
    stub_ops = yaml.safe_load((DEMO_B / "evals" / f"{case}.yaml").read_text(encoding="utf-8"))["stub_answer"]["ops"]
    quote = stub_ops[0]["evidence"]["quote"]
    report = _run_with(
        case,
        {"summary": "Noted it.", "ops": [{"op": "fact", "text": quote, "evidence": {"quote": quote}}]},
        monkeypatch,
    )
    assert report.results and not report.results[0].passed


def test_a_question_on_who_does_a_to_do_the_answer_gave_the_person_fails_its_golden_case(monkeypatch):
    """The stronger model's slip: the to-do is the person's, and a question asks who should do it."""
    case = "own-note-to-do-given-to-me-asks-no-who"
    answer = yaml.safe_load((DEMO_B / "evals" / f"{case}.yaml").read_text(encoding="utf-8"))["stub_answer"]
    answer["ops"].append(
        {
            "op": "question.add",
            "to": "me",
            "title": "Who should send the cover brief?",
            "text": "Who should send it, and by what date?",
            "project": "PRJ-1",
            "would_change": {"what": "owner", "record": "$new:0"},
        }
    )
    report = _run_with(case, answer, monkeypatch)
    assert report.results and not report.results[0].passed
