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
