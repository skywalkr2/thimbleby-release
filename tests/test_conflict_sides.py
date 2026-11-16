"""A question about a conflict says whose words each side is (S-0546): each side cites its source, author and date and
gives the exact words, and a quote that isn't in its cited source is refused with the evidence check's own test. The
assistant's own summary is never quoted as a source. Names and ids come from the evaluation case."""

from __future__ import annotations

import copy
import json

import pytest

from engine.ai.adapters.stub import set_responder
from engine.applier import Context, Inputs, check
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_A
from tests.test_evaluate_harness import case_of, run_edited

CASE = "conflict-question-cites-each-side"
CHECK = "conflict-sides"
SPEC = case_of(DEMO_A, CASE)
GOOD = SPEC["stub_answer"]["ops"][0]
RECORD_SIDE, INPUT_SIDE = GOOD["sides"]
RAW = SPEC["pasted"]
RECORD_ID = RECORD_SIDE["source"]


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_A, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    from engine.evaluate import _create_starting_records

    _create_starting_records(store, CASE, [r for r in SPEC["given"] if r["kind"] == "fact"])
    yield cfg, store
    store.close()
    set_responder(None)


def problems(env, op: dict, *, actor: str = "assistant") -> list[str]:
    cfg, store = env
    cs = CHANGESET.validate_python({"ops": [op]}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs("REQ-1", "SRC-1", RAW, "", "untrusted"),
        actor=actor,
    )
    return [p.message for p in check(cs, ctx) if p.check == CHECK]


def edited(**changes) -> dict:
    op = copy.deepcopy(GOOD)
    op.update(changes)
    return op


def fact_id(env) -> str:
    _, store = env
    return next(f.id for f in store.read().list("fact") if "Rollout plan" in f.data["text"])


def test_a_question_citing_each_side_by_its_source_is_accepted(env):
    op = edited()
    for side in op["sides"]:
        if side["source"] == RECORD_ID:
            side["source"] = fact_id(env)
    assert problems(env, op) == []


def test_a_quote_that_is_not_in_its_cited_source_is_refused(env):
    op = edited()
    op["sides"][0]["source"] = fact_id(env)
    op["sides"][0]["quote"] = "the pilot starts on 2027-02-01"
    op["text"] = op["text"].replace("the pilot starts on 2027-01-11", "the pilot starts on 2027-02-01")
    assert any("isn't in" in p and "copy the words exactly" in p for p in problems(env, op))


def test_a_quote_from_the_input_that_is_not_in_the_input_is_refused(env):
    op = edited()
    op["sides"][1]["quote"] = "the pilot starts at the end of the year"
    assert any("isn't in input" in p for p in problems(env, op))


def test_a_record_side_quoting_words_only_the_input_holds_is_refused(env):
    """A side's words must be in the source it names: words the input holds don't prove what a record says."""
    op = edited()
    op["sides"][0]["source"] = fact_id(env)
    op["sides"][0]["quote"] = INPUT_SIDE["quote"]
    op["sides"][1] = copy.deepcopy(INPUT_SIDE)
    assert any("isn't in" in p and "copy the words exactly" in p for p in problems(env, op))


def test_a_side_cites_a_record_or_the_input_never_something_else(env):
    op = edited()
    op["sides"][0]["source"] = "the direction recorded for this project"
    assert any("isn't a record or the input" in p for p in problems(env, op))


def test_a_question_about_a_conflict_with_fewer_than_two_sides_is_refused(env):
    assert any("gives each side" in p for p in problems(env, edited(sides=[])))
    assert any("gives each side" in p for p in problems(env, edited(sides=[INPUT_SIDE])))


def test_the_text_must_show_each_sides_words(env):
    op = edited(text="Which start day holds?")
    assert sum("doesn't show the words" in p for p in problems(env, op)) == 2


def test_a_phrase_quoted_that_no_side_says_is_refused(env):
    op = edited()
    op["text"] += ' The direction is "the direction recorded for this project".'
    assert any("is from none of the sides' sources" in p for p in problems(env, op))


def test_a_side_is_never_authored_by_the_assistant(env):
    cfg, _ = env
    op = edited()
    op["sides"][0]["author"] = cfg.workspace.assistant_name
    assert any("never the assistant" in p for p in problems(env, op))


def test_the_persons_own_questions_are_left_alone(env):
    assert problems(env, edited(sides=[]), actor="pm") == []


def test_the_case_passes_and_fails_without_a_side_or_with_a_made_up_quote(monkeypatch):
    assert run_edited(monkeypatch, DEMO_A, CASE).passed
    sideless = json.loads(json.dumps(SPEC["stub_answer"]))
    sideless["ops"][0]["sides"] = []
    assert not run_edited(monkeypatch, DEMO_A, CASE, stub_answer=sideless).passed
    invented = json.loads(json.dumps(SPEC["stub_answer"]))
    invented["ops"][0]["sides"][0]["quote"] = "the pilot starts whenever the vendor is ready"
    assert not run_edited(monkeypatch, DEMO_A, CASE, stub_answer=invented).passed
