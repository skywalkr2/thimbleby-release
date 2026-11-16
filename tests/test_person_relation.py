"""How a person relates, proposed from what a message says (S-0531, design 6.22, "Learning the person from their mail
and calendar"): the notes run of one message may propose a relation for someone on file with the exact words as
evidence. It waits for the person's yes; nothing about the person's record changes before it. Names and ids come from
the fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine.applier import Context, Inputs, apply_changeset, decline_held, release
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_A, DEMO_B, fixture_records

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
_TEST = WriteContext(actor="pm", trust="trusted", op="test.relation")
CASES = ("relation-said-in-the-message-is-proposed-with-its-words", "no-relation-said-proposes-none")


class Clock:
    def __call__(self) -> str:
        return NOW.isoformat(timespec="seconds")


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"})
    store = Store(ws.db_path, cfg=cfg, clock=Clock())
    yield ws, cfg, store
    store.close()


def someone(store) -> tuple[str, str]:
    """A person on file who is not the user, with their name."""
    found = next(p for p in store.read().list("person") if p.data.get("relation") is None)
    return found.id, found.data["full_name"]


def apply(env, ops, raw, actor="assistant", trust="untrusted"):
    _, cfg, store = env
    cs = CHANGESET.validate_python({"ops": ops}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs("REQ-1", None, raw, "", trust, cites="mail:1"),
        actor=actor,
    )
    cs_id = apply_changeset(cs, [], ctx, run=None, now=NOW)
    return cs_id, store.read().get("changeset", cs_id).data["ops"]


def relation_op(person, quote, value="our accountant"):
    return {
        "op": "record.set",
        "kind": "person",
        "id": person,
        "field": "relation",
        "value": value,
        "evidence": {"quote": quote},
    }


def test_a_relation_from_a_message_waits_for_the_persons_yes_and_changes_nothing_before_it(env):
    _, cfg, store = env
    who, name = someone(env[2])
    words = f"{name} is our accountant these days"
    cs_id, (outcome,) = apply(env, [relation_op(who, words)], raw=f"From: Dana\n\n{words}.")
    assert outcome["status"] == "held" and "only you can set relation" in outcome["reason"]
    assert outcome["op"]["evidence"]["quote"] == words  # the exact words travel with the proposal
    assert store.read().get("person", who).data.get("relation") is None  # nothing changed before the yes
    release(store, cfg, cs_id, 0)
    assert store.read().get("person", who).data["relation"] == "our accountant"


def test_leaving_the_proposed_relation_sets_none_and_is_a_signal(env):
    _, cfg, store = env
    who, name = someone(store)
    words = f"{name} is our accountant these days"
    cs_id, _ = apply(env, [relation_op(who, words)], raw=words)
    decline_held(store, cs_id, 0)
    assert store.read().get("person", who).data.get("relation") is None
    assert [s for s in store.read().list("signal") if s.data["kind"] == "held_declined"]


def test_a_relation_with_no_words_behind_it_or_words_that_are_not_in_the_message_is_refused(env):
    _, _, store = env
    who, name = someone(store)
    words = f"{name} is our accountant these days"
    bare = relation_op(who, words)
    del bare["evidence"]
    for op, raw in ((bare, words), (relation_op(who, "my sister, for sure"), words)):
        _, (outcome,) = apply(env, [op], raw=raw)
        assert outcome["status"] == "refused", outcome
    assert store.read().get("person", who).data.get("relation") is None


def test_the_persons_own_note_sets_the_relation_at_once(env):
    _, _, store = env
    who, name = someone(store)
    _, (outcome,) = apply(
        env, [relation_op(who, "my neighbor", "my neighbor")], raw="my neighbor", actor="pm", trust="trusted"
    )
    assert outcome["status"] == "applied"
    assert store.read().get("person", who).data["relation"] == "my neighbor"


@pytest.mark.parametrize("template", [DEMO_A, DEMO_B], ids=["demo-a", "demo-b"])
@pytest.mark.parametrize("case_id", CASES)
def test_the_relation_cases_pass_with_their_ideal_answer(monkeypatch, template, case_id):
    from tests.test_evaluate_harness import run_edited

    result = run_edited(monkeypatch, template, case_id)
    assert result.passed, (result.missing, result.forbidden)


def test_an_answer_that_proposes_a_relation_from_being_copied_fails_the_case_and_one_without_the_words_does_too(
    monkeypatch,
):
    from tests.test_evaluate_harness import case_of, run_edited

    quiet = case_of(DEMO_B, "no-relation-said-proposes-none")
    said = case_of(DEMO_B, "relation-said-in-the-message-is-proposed-with-its-words")
    person = said["stub_answer"]["ops"][0]["id"]
    name = next(p["full_name"] for p in fixture_records(DEMO_B, "person") if p["id"] == person)
    guessed = relation_op(person, f"I copied {name} on the year-end invoices", "our accountant")
    result = run_edited(monkeypatch, DEMO_B, quiet["id"], stub_answer={"summary": "x", "ops": [guessed]})
    assert not result.passed and result.forbidden
    nothing = run_edited(monkeypatch, DEMO_B, said["id"], stub_answer={"summary": "x", "ops": []})
    assert not nothing.passed
