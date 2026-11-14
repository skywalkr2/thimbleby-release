"""A vague question is never asked (design 6.7): a question that asks something wide open ("what should have
happened?"), quotes nothing the assistant saw and offers no choices goes back once (`vague-question`, a judgment
lint). The words that open such a question and the words that offer choices are language settings. Names come from the
fixtures."""

from __future__ import annotations

import pytest

from engine.applier import JUDGMENT_LINTS, Context, Inputs, check
from engine.evaluate import load_cases
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_A, DEMO_B, fixture_records

PERSON = fixture_records(DEMO_B, "person")[0]["full_name"]
EXAMPLE_HOST = "example.com"
NOTICE = "Notice: your order of 200 paperbacks is paused until the order is changed."


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def found(env, op, raw=NOTICE):
    _, cfg, store = env
    cs = CHANGESET.validate_python({"ops": [{"op": "question.add", "to": PERSON, **op}]})
    ctx = Context(store, cfg, People(store, cfg), ("question.add",), Inputs("REQ-1", None, raw, raw, "untrusted"))
    return [p for p in check(cs, ctx) if p.check == "vague-question"]


def test_the_lint_is_a_judgment_lint_that_returns_by_default_in_both_fictional_workspaces(env):
    from engine.config import load_config

    _, cfg, _ = env
    assert "vague-question" in JUDGMENT_LINTS and cfg.checks.lints["vague-question"] == "return"
    for template in (DEMO_A, DEMO_B):
        assert load_config(template / "config", env={}).checks.lints["vague-question"] == "return"


@pytest.mark.parametrize(
    "title",
    [
        "Order notice: what should have happened?",
        "What should happen with the order?",
        "What do you want to do about it?",
        "What happened to the order?",
    ],
)
def test_an_open_question_that_quotes_nothing_and_offers_no_choice_is_returned(env, title):
    (problem,) = found(env, {"title": title, "text": "There was a notice."})
    assert problem.severity == "return" and problem.op == 0
    assert "what was seen" in problem.message and "choices" in problem.message


def test_a_question_that_quotes_what_was_seen_is_not_vague(env):
    text = 'The notice says "your order of 200 paperbacks is paused".'
    assert found(env, {"title": "What should happen with the order?", "text": text}) == []


def test_a_question_that_offers_choices_is_not_vague(env):
    op = {"title": "What should happen with the order?", "text": "Ship what is in stock, or wait for all 200."}
    assert found(env, op) == []
    assert found(env, {"title": "What should we do: ship now or wait?", "text": ""}) == []


def test_a_question_that_is_not_open_is_not_returned(env):
    assert found(env, {"title": "Is the order of 200 paperbacks still wanted?", "text": ""}) == []


def test_a_question_about_a_word_is_never_vague(env):
    assert found(env, {"title": "What should this word mean here?", "text": "", "term": "WORD"}) == []


def test_the_words_are_language_settings_not_code(env):
    _, cfg, _ = env
    op = {"title": "Whatever shall we do?", "text": ""}
    assert found(env, op) == []
    cfg.language.open_question_phrases = ["whatever shall we"]
    assert len(found(env, op)) == 1
    cfg.language.choice_words = ["shall"]
    assert found(env, op) == []


def test_the_golden_case_asks_with_the_quote_and_the_choices_and_passes_the_lint(env):
    case = next(c for c in load_cases(DEMO_B) if c["id"] == "a-question-says-what-was-seen-and-offers-choices")
    (ideal,) = case["stub_answer"]["ops"]
    quoted = ideal["text"].split('"')[1]
    assert quoted in case["pasted"], "the question quotes words that are in the notice"
    op = {k: v for k, v in ideal.items() if k not in ("op", "to")}
    assert found(env, op, raw=case["pasted"]) == []
    vague = {"title": "Order notice: what should have happened?", "text": ""}
    assert len(found(env, vague, raw=case["pasted"])) == 1


def test_a_question_that_points_at_an_item_without_naming_it_is_returned_to_name_link_and_say_what_is_recorded(env):
    (problem,) = found(env, {"title": "Is this item still wanted?", "text": "It was in the list."})
    assert problem.severity == "return" and "exact title" in problem.message


def test_a_question_that_names_the_items_title_or_links_it_is_not_returned(env):
    quoted = 'The notice says "your order of 200 paperbacks is paused".'
    assert found(env, {"title": "Is this item still wanted?", "text": quoted}) == []
    linked = {
        "title": "Is this item still wanted?",
        "text": "",
        "links": [{"label": "The order", "url": "https://" + EXAMPLE_HOST + "/o"}],
    }
    assert found(env, linked) == []
    assert found(env, {"title": "Is the order of 200 paperbacks still wanted?", "text": ""}) == []


def test_the_pointing_words_are_a_language_setting(env):
    _, cfg, _ = env
    assert found(env, {"title": "Is that thing still wanted?", "text": ""}) == []
    cfg.language.unnamed_item_phrases = ["that thing"]
    assert len(found(env, {"title": "Is that thing still wanted?", "text": ""})) == 1


def test_the_golden_case_for_one_item_names_its_title_and_passes_the_lint(env):
    case = next(c for c in load_cases(DEMO_B) if c["id"] == "a-question-about-one-item-names-its-title")
    (ideal,) = case["stub_answer"]["ops"]
    op = {k: v for k, v in ideal.items() if k not in ("op", "to")}
    assert found(env, op, raw=case["pasted"]) == []
    assert len(found(env, {"title": "Is this item still wanted?", "text": ""}, raw=case["pasted"])) == 1
