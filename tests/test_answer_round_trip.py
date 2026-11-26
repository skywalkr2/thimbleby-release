"""Every field an answer can carry comes out the other side: a field the parser drops is information the model gave
and the product threw away, and a unit test that skips the parse never sees it.

A known-good answer carrying every field, with one problem that sends it back, goes in through the stand-in AI: the
dispatcher's real parse reads it, the return round shows it as "Your previous answer", the second answer is that shown
answer copied with only the problem fixed, and the applier records it. Each field is then checked where it lands. A
field added to the answer fails here until it has a place in `LANDS`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.dispatcher import parse, process
from engine.intake import hand_in
from engine.ops import ChangesetIn
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records, without_first_go

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
PM = fixture_records(DEMO_B, "person")[0]["id"]
NOTE = "We also need to send the fair sponsor thank-you letters."
SHOWN = "Your previous answer (its ops are numbered from 0):\n"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    without_first_go(ws.config_dir)
    cfg = ws.config(env={}, flags={"storage.backups.automatic": False})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()
    set_responder(None)


def learned(store) -> str:
    """An active lesson for the whole workspace with a kind of work, so every run is given it."""
    with store.transaction() as tx:
        return tx.create(
            "lesson",
            {
                "text": "The fair invitations are the user's to send.",
                "kind_of_work": "what goes out for the fair",
                "origin": "person",
                "status": "active",
                "learned_at": NOW.isoformat(),
                "kept_by": PM,
                "kept_at": NOW.isoformat(),
                "applies_to": {},
            },
            WriteContext("pm", "trusted", "test"),
        ).id


def answer(entry: str) -> dict:
    """A known-good answer with every field set, and one problem: a question that names nothing its answer changes."""
    return {
        "summary": "Added the sponsor letters, and asked when they go out.",
        "topic": "fair sponsor letters",
        "ops": [
            {"op": "action.add", "text": "Send the fair sponsor thank-you letters", "evidence": {"quote": NOTE}},
            {
                "op": "question.add",
                "to": PM,
                "title": "When do the fair sponsor letters go out?",
                "text": "The letters have no day yet.",
                # Not a date question: one date question for an answer's undated to-dos settles their days, which is
                # no problem; any other question naming nothing it changes still is.
                "asks_about": "other",
            },
        ],
        "ask": False,
        "applied": [entry],
        "by_kind": [{"op": 0, "entry": entry}],
        "missing": ["An op to send the letters to every sponsor at once."],
        "omitted": [{"op": "note", "reason": "The letters are the to-do; a note would repeat it."}],
    }


#: Where each field of an answer lands once applied, read from the changeset record (and the to-do it made).
LANDS = {
    "summary": lambda cs, store, given: cs["summary"] == given["summary"],
    "topic": lambda cs, store, given: cs["topic"] == given["topic"],
    "ops": lambda cs, store, given: [o["op"]["op"] for o in cs["ops"]] == ["action.add", "question.add"],
    "applied": lambda cs, store, given: cs["applied"] == given["applied"],
    "by_kind": lambda cs, store, given: (
        cs["ops"][0]["by_kind"]["entry"] == given["by_kind"][0]["entry"]
        and store.read().get("action", cs["ops"][0]["records"][0]["id"]).data["by_kind"]["entry"]
        == given["by_kind"][0]["entry"]
    ),
    "missing": lambda cs, store, given: cs["missing"] == given["missing"],
    "omitted": lambda cs, store, given: cs["omitted"] == given["omitted"],
    # `ask` makes a note a question to the assistant, so an answer with ops never lands it; it survives both readings
    # (checked below), and the own-note branch that reads it is tested in tests/test_pipeline.py.
    "ask": None,
}


def test_every_field_an_answer_can_carry_has_a_place_it_lands():
    assert set(ChangesetIn.model_fields) == set(LANDS), set(ChangesetIn.model_fields) ^ set(LANDS)


def test_every_field_survives_the_parse_and_the_return_rounds_previous_answer():
    given = {**answer("LES-1"), "ask": True}
    first = parse(json.dumps(given))
    from engine.dispatcher import _answer_shown

    again = parse(_answer_shown(first)[len(SHOWN) :])
    for name in LANDS:
        assert getattr(again, name) == getattr(first, name), name
        assert getattr(first, name) not in ("", [], False, None), f"{name} was dropped by the parse"


def test_every_field_comes_out_the_other_side_of_a_return_round_and_the_applier(env):
    ws, cfg, store = env
    entry = learned(store)
    given = answer(entry)
    rounds: list[str] = []

    def respond(task):
        rounds.append(task.request)
        if len(rounds) == 1:
            return json.dumps(given)
        # The second answer is the previous answer exactly as it was shown, with only the problem fixed.
        assert SHOWN in task.request, "the return round shows the previous answer"
        shown = task.request.split(SHOWN, 1)[1]
        previous = json.JSONDecoder().raw_decode(shown)[0]
        previous["ops"][1]["would_change"] = {"what": "field", "record": "$new:0", "field": "due"}
        return json.dumps(previous)

    set_responder(respond)
    request = hand_in(ws, store, note=NOTE, now=NOW).request
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), request, now=NOW)
    assert len(rounds) == 2, "the known-good answer's one problem sends it back once"
    stored = store.read().get("changeset", cs_id).data
    for name, lands in LANDS.items():
        if lands is not None:
            assert lands(stored, store, given), (name, {k: stored.get(k) for k in ("summary", "topic", name)})
