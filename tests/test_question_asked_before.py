"""A question that was answered or dropped is never asked again (design 6.8): each question has a key (whom it
is for and its subject); a new question with the key of a closed one is refused with the earlier answer quoted, a newer
source that contradicts the answer is asked as a conflict, the person can ask a dropped question again, and what the
answer should change is kept on the question and given to the run that handles the answer. Built on the search tests'
workspace; names and ids come from the fixtures."""

from __future__ import annotations

from engine.applier import apply_as_person, question_key
from engine.storage import WriteContext
from tests.test_search import OPEN_QUESTION, add_question, env, pm_id, problems_for, question_op  # noqa: F401

_PM = WriteContext("pm", "trusted", "test")


def refused(env, title=OPEN_QUESTION, actor="assistant", **more):  # noqa: F811  # noqa: F811
    _, cfg, _ = env
    return problems_for(env, question_op(cfg, title, **more), "question-asked-before", actor=actor)


def close(store, qid, status, **more):
    with store.transaction() as tx:
        cur = tx.get("question", qid)
        tx.update("question", qid, {"status": status, **more}, _PM, read_version=cur.version)


def test_the_key_is_the_person_and_the_words_of_the_subject_in_any_order():
    assert question_key("PER-1", "Which printer takes the hardcover run?") == question_key(
        "PER-1", "the hardcover run: takes which printer"
    )  # the words, not their order
    assert question_key("PER-1", "Which printer takes the run") == question_key("PER-1", "which PRINTER takes the run?")
    assert question_key("PER-1", "Which printer takes the run") != question_key("PER-2", "Which printer takes the run")
    assert question_key("PER-1", "Which printer takes the run") != question_key("PER-1", "Which binder takes the run")


def test_a_dropped_question_is_never_asked_again_and_the_reason_is_quoted(env):  # noqa: F811
    _, _, store = env
    qid = add_question(store, OPEN_QUESTION, status="dropped", dropped_reason="Settled on a call")
    (problem,) = refused(env)
    assert problem.severity == "refuse" and qid in problem.message and "Settled on a call" in problem.message
    assert not refused(env, "Which binder takes the hardcover run")  # another subject is a new question
    assert not refused(env, actor="pm")  # the person's own question is theirs to ask


def test_an_answered_question_is_refused_for_good_with_its_answer_quoted(env):  # noqa: F811
    _, _, store = env
    store.clock = lambda: "2026-01-01T09:00:00+00:00"
    qid = add_question(store, OPEN_QUESTION)
    close(store, qid, "answered", answer="The usual one.")
    store.clock = lambda: "2027-06-01T09:00:00+00:00"  # long after any days window
    (problem,) = refused(env)
    assert qid in problem.message and "The usual one." in problem.message


def test_an_open_question_is_not_refused_here_the_near_duplicate_lint_handles_it(env):  # noqa: F811
    _, _, store = env
    add_question(store, OPEN_QUESTION)
    assert not refused(env)


def test_a_newer_source_that_contradicts_the_answer_is_asked_as_a_conflict(env):  # noqa: F811
    _, cfg, store = env
    store.clock = lambda: "2026-10-01T09:00:00+00:00"
    qid = add_question(store, OPEN_QUESTION)
    close(store, qid, "answered", answer="The usual one.")
    store.clock = lambda: "2026-11-01T09:00:00+00:00"
    with store.transaction() as tx:
        newer = tx.create(
            "source",
            {
                "received_at": "2026-10-20T09:00:00+00:00",
                "kind": "pasted",
                "title": "A later message",
                "content_hash": "1" * 64,
                "trust": "untrusted",
            },
            _PM,
        ).id
    from engine.applier import Context, Inputs
    from engine.names import People
    from engine.ops import CHANGESET

    def run(asks_about):
        cs = CHANGESET.validate_python(
            {"ops": [question_op(cfg, OPEN_QUESTION, asks_about=asks_about)]}, context={"op_models": store.plugins.ops}
        )
        ctx = Context(
            store,
            cfg,
            People(store, cfg),
            ("question.add",),
            Inputs("REQ-1", newer, "", "", "trusted"),
            actor="assistant",
        )
        from engine.applier import check

        return [p for p in check(cs, ctx) if p.check == "question-asked-before"]

    assert run("other")  # a newer input alone is not a contradiction: the question is still refused
    assert not run("mistake")  # asked as a conflict, it files


def test_ask_again_opens_a_dropped_question_and_only_a_dropped_one(env):  # noqa: F811
    _, cfg, store = env
    dropped = add_question(store, OPEN_QUESTION, status="dropped", dropped_reason="Not needed")
    opened = add_question(store, "Which binder takes the run")
    apply_as_person(store, cfg, [{"op": "question.ask_again", "id": dropped}], "Asked again")
    assert store.read().get("question", dropped).data["status"] == "open"
    assert store.read().get("question", dropped).data["dropped_reason"] is None
    try:
        apply_as_person(store, cfg, [{"op": "question.ask_again", "id": opened}], "Asked again")
    except Exception as err:
        assert "wasn't dropped" in str(err)
    else:  # pragma: no cover
        raise AssertionError("an open question can't be asked again")


def test_the_assistant_can_never_ask_again(env):  # noqa: F811
    _, cfg, store = env
    from engine.applier import Context, Inputs, check
    from engine.names import People
    from engine.ops import CHANGESET

    dropped = add_question(store, OPEN_QUESTION, status="dropped")
    cs = CHANGESET.validate_python({"ops": [{"op": "question.ask_again", "id": dropped}]})
    ctx = Context(
        store, cfg, People(store, cfg), ("question.ask_again",), Inputs("R", None, "", "", "trusted"), actor="assistant"
    )
    assert {p.check for p in check(cs, ctx) if p.severity == "refuse"}


def test_what_the_answer_should_change_is_kept_and_given_to_the_run_that_handles_the_answer(env):  # noqa: F811
    _, cfg, store = env
    from engine import packet
    from engine.applier import Context, Inputs, apply_changeset
    from engine.names import People
    from engine.ops import CHANGESET

    cs = CHANGESET.validate_python(
        {"ops": [question_op(cfg, "Which trim size for the paperback", to=pm_id(cfg))]},
        context={"op_models": store.plugins.ops},
    )
    ctx = Context(
        store, cfg, People(store, cfg), ("question.add",), Inputs("REQ-1", None, "", "", "trusted"), actor="pm"
    )
    apply_changeset(cs, [], ctx, run=None)
    (question,) = [q for q in store.read().list("question") if q.data["title"].startswith("Which trim size")]
    assert question.data["would_change"] == {"what": "setting", "setting": "ui.today.stale_after_days"}
    assert question.data["key"] == question_key(pm_id(cfg), question.data["title"])
    from types import SimpleNamespace

    request = SimpleNamespace(data={"about": {"kind": "question", "id": question.id}})
    note = SimpleNamespace(data={"kind": "note:answered"})
    block = packet._item_block(None, store, cfg, request, note)  # noqa: SLF001 - the block the answer's run is given
    assert '"would_change": {"setting": "ui.today.stale_after_days", "what": "setting"}' in block
