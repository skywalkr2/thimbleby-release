"""An open question reaches the assistant with its detail and the keys it names, so an input that settles the problem
it asks about can close it (design 6.8)."""

from __future__ import annotations

from pathlib import Path

from engine import evaluate as ev
from engine.ai.adapters import stub

DEMO = Path(__file__).resolve().parent.parent / "workspaces" / "demo-a"
CLOSES = "question-settled-by-a-fix-is-closed"
STAYS = "question-about-another-ticket-stays-open"


def _tasks_of(case: str, monkeypatch) -> list:
    seen: list = []

    def spy(responder):
        if responder is None:
            return stub.set_responder(None)

        def wrapped(task):
            seen.append(task)
            return responder(task)

        stub.set_responder(wrapped)

    monkeypatch.setattr(ev, "set_responder", spy)
    report = ev.evaluate(DEMO, stub=True, runs=1, only=[case])
    assert report.results and all(r.passed for r in report.results)
    return seen


def _line(case: str, monkeypatch) -> str:
    stable = _tasks_of(case, monkeypatch)[0].stable
    section = stable.split("# Open questions")[1].split("# People")[0]
    return next(ln for ln in section.splitlines() if ln.startswith("- Q-90 "))


def test_the_packet_gives_a_questions_detail_and_the_keys_it_names(monkeypatch):
    line = _line(CLOSES, monkeypatch)
    assert "names T-1" in line
    assert "Dates on the depot sheet arrive a day early (ticket T-1)" in line


def test_a_question_that_names_nothing_shows_no_keys_and_a_long_detail_is_cut(monkeypatch):
    from engine import packet

    class _Rec:
        id = "Q-1"

        def __init__(self, data):
            self.data = data

    class _View:
        def list(self, kind):
            return [_Rec({"status": "open", "to": "P", "title": "Which printer?", "text": "x " * 500})]

        def get(self, *a, **k):
            return None

    class _Store:
        def read(self):
            return _View()

    class _People:
        def name(self, pid):
            return "Pat"

    monkeypatch.setattr(packet, "_marked_if_outside", lambda view, rec, words: words)
    line = packet._open_questions(_Store(), _People(), None, 50)
    assert "names" not in line and line.endswith("...") and len(line) < 150
    assert "detail" not in packet._open_questions(_Store(), _People(), None, 0)
