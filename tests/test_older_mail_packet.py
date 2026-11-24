"""Older mail is read to learn about the person's life: its packet says so, and a recent input's does not."""

from __future__ import annotations

import json
from pathlib import Path

from engine import evaluate as ev
from engine.ai.adapters import stub

DEMO = Path(__file__).resolve().parent.parent / "workspaces" / "demo-a"
OLDER = "older-mail-teaches-about-the-persons-life"
RECENT = "unpaid-bill-past-due-stays-a-todo"


def _requests_of(case: str, monkeypatch) -> str:
    seen: list[str] = []

    def spy(responder):
        if responder is None:
            return stub.set_responder(None)

        def wrapped(task):
            seen.append(task.request)
            return responder(task)

        stub.set_responder(wrapped)

    monkeypatch.setattr(ev, "set_responder", spy)
    report = ev.evaluate(DEMO, stub=True, runs=1, only=[case])
    assert report.results and all(r.passed for r in report.results)
    return "\n".join(seen)


def test_the_older_reads_request_says_what_it_is_for(monkeypatch):
    assert "read to learn about the user's life" in _requests_of(OLDER, monkeypatch)


def test_a_recent_inputs_request_does_not(monkeypatch):
    assert "read to learn about the user's life" not in _requests_of(RECENT, monkeypatch)


# A real low-cost model's answers to the packets of these cases, scored by each case's own checks.
ANSWERS = DEMO / "evals" / "real-answers"
#: Every workspace with real answers of its own: the second demo holds the reviewer's draft-request case.
DEMOS = [DEMO, DEMO.parent / "demo-b"]


def _score(case: str, monkeypatch, demo: Path = DEMO):
    """Score a real model's saved answers to a case. A file holding a list is the answers of each round in order (the
    first answer, then its answer to the problems sent back), as the app gets them; the last answers any later call."""
    found = json.loads((demo / "evals" / "real-answers" / f"{case}.json").read_text(encoding="utf-8"))
    rounds = [json.dumps(a) for a in found] if isinstance(found, list) else [json.dumps(found)]
    calls = iter(range(10_000))

    def answer(task):
        return rounds[min(next(calls), len(rounds) - 1)]

    def replace(responder):
        stub.set_responder(None if responder is None else answer)

    monkeypatch.setattr(ev, "set_responder", replace)
    return ev.evaluate(demo, stub=True, runs=1, only=[case])


def test_a_real_models_answers_pass_the_cases_checks(monkeypatch):
    for path in sorted(p for demo in DEMOS for p in (demo / "evals" / "real-answers").glob("*.json")):
        report = _score(path.stem, monkeypatch, path.parent.parent.parent)
        assert report.results, path.stem
        failed = [r for r in report.results if not r.passed]
        assert not failed, (path.stem, [getattr(r, "reasons", r) for r in failed])
