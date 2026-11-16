"""A reply handed in against a question that went out, holding a question of its own (S-0545): the run drafts the
answer first (a reply owed with its draft), asks the replier nothing new, and records a confirmation as one. The rule is
on the reply's words and the person the question was asked of, with no AI. Names and ids come from the fixtures and
the evaluation case."""

from __future__ import annotations

import json

import pytest

from engine.ai.adapters.stub import set_responder
from engine.applier import Context, Inputs, check
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_A, DEMO_B, fixture_records
from tests.test_evaluate_harness import case_of, run_edited, with_ops

CHECK = "reply-question-first"
CASE = "reply-with-a-question-is-answered-first"
QUESTION = fixture_records(DEMO_B, "question")[0]
ASKED = next(p for p in fixture_records(DEMO_B, "person") if p["id"] == QUESTION["to"])
OTHER = next(p for p in fixture_records(DEMO_B, "person") if p["id"] not in (QUESTION["to"], "PER-1", "PER-2001"))
PROJECT = fixture_records(DEMO_B, "project")[0]["id"]
HOLDS_QUESTION = f"From: {ASKED['full_name']}\n\nYes, that is final. Where did you see the extra names mentioned?\n"
NO_QUESTION = f"From: {ASKED['full_name']}\n\nYes, that is final. No more names are coming.\n"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()
    set_responder(None)


def a_reply(store, *, answers: str | None) -> str:
    from engine.storage import WriteContext

    with store.transaction() as tx:
        return tx.create(
            "request",
            {
                "task": "notes",
                "origin": "pm",
                "state": "queued",
                "created_at": "2026-10-14T09:00:00+00:00",
                **({"answers": answers} if answers else {}),
            },
            WriteContext(actor="pm", trust="trusted", op="test"),
        ).id


def asking(to: str, text: str = "Which names are left?") -> dict:
    return {
        "op": "question.add",
        "to": to,
        "title": "Which names are left?",
        "text": text,
        "project": PROJECT,
        "would_change": {"what": "field", "record": QUESTION["id"], "field": "title"},
        "matters_for": "the acknowledgments page",
    }


def drafting() -> dict:
    return {
        "op": "action.add",
        "text": f"Tell {ASKED['full_name']} where the extra names were mentioned",
        "owners": ["PER-1"],
        "project": PROJECT,
        "reply_owed": True,
        "reply": "They were in the printer's proof list.",
        "evidence": {"quote": "Where did you see the extra names mentioned?"},
    }


def found(env, ops: list[dict], raw: str, *, answers: str | None, actor: str = "assistant") -> list:
    _, cfg, store = env
    request = a_reply(store, answers=answers)
    cs = CHANGESET.validate_python({"ops": ops}, context={"op_models": store.plugins.ops})
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request, "SRC-1", raw, "", "untrusted"),
        actor=actor,
    )
    return [p for p in check(cs, ctx) if p.check == CHECK]


def test_a_question_to_the_replier_is_refused_when_the_reply_asked_one_and_nothing_was_drafted(env):
    (problem,) = found(env, [asking(ASKED["id"])], HOLDS_QUESTION, answers=QUESTION["id"])
    assert (problem.severity, problem.op) == ("return", 0)
    assert "drafts the answer first" in problem.message and "Where did you see" in problem.message


def test_a_question_to_the_replier_is_refused_even_beside_the_draft(env):
    (problem,) = found(env, [drafting(), asking(ASKED["id"])], HOLDS_QUESTION, answers=QUESTION["id"])
    assert (problem.severity, problem.op) == ("return", 1)
    assert "nothing new" in problem.message


def test_the_severity_setting_is_honoured(env):
    _, cfg, _ = env
    cfg.checks.lints[CHECK] = "off"
    assert found(env, [asking(ASKED["id"])], HOLDS_QUESTION, answers=QUESTION["id"]) == []
    cfg.checks.lints[CHECK] = "warn"
    (problem,) = found(env, [asking(ASKED["id"])], HOLDS_QUESTION, answers=QUESTION["id"])
    assert problem.severity == "warn"


@pytest.mark.parametrize(
    "case",
    ["no question in the reply", "a question to someone else", "not a reply", "the person's own change", "no asker"],
)
def test_everything_else_is_left_alone(env, case):
    ops = [asking(OTHER["id"] if case == "a question to someone else" else ASKED["id"])]
    raw = NO_QUESTION if case == "no question in the reply" else HOLDS_QUESTION
    answers = None if case == "not a reply" else ("Q-9999" if case == "no asker" else QUESTION["id"])
    assert found(env, ops, raw, answers=answers, actor="pm" if case == "the person's own change" else "assistant") == []


def test_a_question_asked_inside_quoted_history_is_not_the_replys_own(env):
    quoted = f"From: {ASKED['full_name']}\n\nYes, that is final.\n\nOn Tue, someone wrote:\n> Is it final?\n"
    assert found(env, [asking(ASKED["id"])], quoted, answers=QUESTION["id"]) == []


def test_the_reply_route_records_which_question_the_input_answers(tmp_path):
    from fastapi.testclient import TestClient

    from api.app import create_app

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"storage.backups.automatic": False})
    app = create_app(ws, cfg, "token", ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": "Bearer token"}) as client:
        posted = client.post(f"/api/questions/{QUESTION['id']}/reply", json={"text": HOLDS_QUESTION})
        assert posted.status_code == 200, posted.text
        request = app.state.store.read().get("request", posted.json()["request"]).data
        assert request["answers"] == QUESTION["id"]
        assert "answers" in request["note"] or QUESTION["id"] in request["note"]


# ---- the evaluation case ---------------------------------------------------------------------------------------------


def test_the_case_passes_when_the_answer_is_drafted_and_the_confirmation_recorded(monkeypatch):
    assert run_edited(monkeypatch, DEMO_A, CASE).passed


def test_the_case_fails_on_a_new_question_a_correction_or_no_draft(monkeypatch):
    case = case_of(DEMO_A, CASE)
    asked = {
        "op": "question.add",
        "to": "PER-3",
        "title": "Route Optimizer Pilot: which depots are in the pilot?",
        "text": "Which depots?",
        "project": "PRJ-4",
        "matters_for": "ACT-15",
        "would_change": {"what": "field", "record": "ACT-15", "field": "text"},
    }
    again = run_edited(monkeypatch, DEMO_A, CASE, stub_answer=with_ops(case, asked))
    assert not again.passed
    lesson = {"op": "lesson.add", "text": "Confirm before asking.", "evidence": {"quote": "the pilot covers the north"}}
    corrected = run_edited(monkeypatch, DEMO_A, CASE, stub_answer=with_ops(case, lesson))
    assert not corrected.passed
    without = json.loads(json.dumps(case["stub_answer"]))
    without["ops"] = [o for o in without["ops"] if o["op"] != "action.add"]
    assert not run_edited(monkeypatch, DEMO_A, CASE, stub_answer=without).passed
