"""A question needs a concrete effect (design 6.22): `question.add` names what its answer would change (a field of a
record, a setting, or the owner of an item), and one that names nothing, or a record that isn't there, is the lint
`question-changes-nothing`. The person's own questions and the app's word questions are never held to it. Names and ids
come from the fixtures."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from engine.applier import Context, Inputs, check
from engine.config import load_config
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_A, DEMO_B, fixture_records

PERSON = fixture_records(DEMO_B, "person")[0]["full_name"]
PROJECT = fixture_records(DEMO_B, "project")[0]["id"]
NOTICE = "Notice: your order of 200 paperbacks is paused until the order is changed."


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    cfg.checks.lints["question-changes-nothing"] = "return"
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def found(env, op, actor="assistant"):
    _, cfg, store = env
    cs = CHANGESET.validate_python({"ops": [{"op": "question.add", "to": PERSON, "title": "Ship now?", **op}]})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        ("question.add",),
        Inputs("REQ-1", None, NOTICE, NOTICE, "untrusted"),
        actor=actor,
    )
    return [p for p in check(cs, ctx) if p.check == "question-changes-nothing"]


def test_the_lint_is_on_by_default_and_both_fictional_workspaces_set_it():
    from engine.config.schema import ChecksFile

    assert ChecksFile().lints["question-changes-nothing"] == "return"
    for template in (DEMO_A, DEMO_B):
        assert load_config(template / "config", env={}).checks.lints["question-changes-nothing"] == "return"


def test_every_question_a_fixture_answer_asks_names_what_it_would_change():
    """The fixtures' answers (evaluations, pairs, scenarios, replays) are held to the lint at full strength: a question
    outside `forbid`, `expect`, `allow` and `differences` (what an answer must or must not hold) names its effect,
    unless it asks what a word means."""
    import yaml

    skipped = {"forbid", "expect", "allow", "differences"}
    bare: list[str] = []

    def walk(node, path, file):
        if isinstance(node, dict):
            asks = node.get("op") == "question.add" and not skipped & set(path) and not node.get("term")
            if asks and "would_change" not in node:
                bare.append(f"{file}: {'.'.join(map(str, path))}")
            for key, value in node.items():
                walk(value, [*path, key], file)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, [*path, i], file)

    for template in (DEMO_A, DEMO_B):
        for folder in ("evals", "pairs", "scenarios", "replays"):
            for file in sorted((template / folder).glob("*.yaml")):
                for doc in yaml.safe_load_all(file.read_text()):
                    walk(doc, [], f"{template.name}/{folder}/{file.name}")
    assert bare == []


def test_a_question_that_names_nothing_its_answer_would_change_is_returned(env):
    (problem,) = found(env, {})
    assert problem.severity == "return" and problem.op == 0
    assert "would_change" in problem.message and "fact or a note" in problem.message


@pytest.mark.parametrize(
    "would_change",
    [
        {"what": "field", "record": PROJECT, "field": "status"},
        {"what": "setting", "setting": "ui.today.stale_after_days"},
        {"what": "owner", "record": PROJECT},
        {"what": "owner", "record": "@1"},  # an item made in the same change can't be looked up yet
    ],
)
def test_a_question_that_names_what_it_would_change_is_not_returned(env, would_change):
    assert found(env, {"would_change": would_change}) == []


def test_a_record_that_is_not_there_is_returned_and_names_it(env):
    (problem,) = found(env, {"would_change": {"what": "owner", "record": "PRJ-99999"}})
    assert "PRJ-99999" in problem.message


@pytest.mark.parametrize(
    "bad",
    [
        {"what": "field", "record": PROJECT},
        {"what": "field", "field": "status"},
        {"what": "owner"},
        {"what": "setting"},
        {"what": "colour", "record": PROJECT},
    ],
)
def test_a_would_change_that_names_too_little_is_refused_as_a_malformed_answer(bad):
    with pytest.raises(ValidationError):
        CHANGESET.validate_python(
            {"ops": [{"op": "question.add", "to": PERSON, "title": "Ship now?", "would_change": bad}]}
        )


def test_a_question_asking_what_a_word_means_and_the_persons_own_question_are_never_held_to_it(env):
    assert found(env, {"title": "", "term": "WORD"}) == []
    assert found(env, {}, actor="pm") == []


def test_the_notes_prompt_asks_for_it_and_says_a_topic_only_match_is_watched_quietly():
    from engine.prompts import render

    text = render("notes", {"assistant_name": "Reginald"})
    assert "would_change" in text and "only by its topic" in text and "ask nothing" in text


@pytest.mark.parametrize(
    "shape",
    [
        {"what": "field", "record": PROJECT},
        "a field of the project",
        {"what": "colour", "record": PROJECT},
    ],
)
def test_an_unreadable_would_change_is_left_out_and_the_question_and_the_rest_of_the_answer_are_kept(shape, caplog):
    from engine.dispatcher import parse

    text = json.dumps(
        {
            "summary": "s",
            "ops": [
                {"op": "question.add", "to": PERSON, "title": "Ship now?", "would_change": shape},
                {"op": "question.add", "to": PERSON, "title": "Other?"},
            ],
        }
    )
    with caplog.at_level("WARNING"):
        cs = parse(text)
    assert len(cs.ops) == 2 and cs.ops[0].title == "Ship now?" and cs.ops[0].would_change is None
    assert sum("would_change left out" in r.message for r in caplog.records) == 1


@pytest.mark.parametrize(
    "shape",
    [
        {"record_id": PROJECT, "field": "status"},
        {"record": PROJECT, "field": "status"},
        {"what": "field", "field": f"{PROJECT}.status"},
        {"setting": "ui.today.stale_after_days"},
    ],
)
def test_plain_shapes_of_would_change_that_mean_the_same_are_read(shape):
    cs = CHANGESET.validate_python(
        {"ops": [{"op": "question.add", "to": PERSON, "title": "Ship now?", "would_change": shape}]}
    )
    assert cs.ops[0].would_change is not None
