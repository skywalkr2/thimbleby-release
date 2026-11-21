"""What the person writes to the assistant about a to-do is read once, for what it means (design 6.7, 7.5): a standing
rule, a change to the to-do, or a request for writing. A payment case: words that state a rule about a kind of mail
and say it is paid by itself, written on an overdue payment to-do. Names and ids come from the fixtures; the AI is
the stub, answering with a real model's recorded answer or the answer the prompt now asks for."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine import action_work
from engine.ai.adapters.stub import set_responder
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

TOKEN = "hand-over-reading"
_PM = WriteContext("pm", "trusted", "test")
OWNER = fixture_records(DEMO_B, "person")[1]["id"]
WORDS = (
    "Any incoming Acme Pay mails should record reminders on the schedule, "
    "but are automatically paid so they should not be to dos"
)
RECORDED = json.loads((Path(__file__).parent / "fixtures" / "hand_over" / "model-answer-1.json").read_text())
RECORDED_3 = (Path(__file__).parent / "fixtures" / "hand_over" / "model-answer-3.json").read_text()
RECORDED_2 = json.loads((Path(__file__).parent / "fixtures" / "hand_over" / "model-answer-2.json").read_text())


@pytest.fixture
def api(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, app.state.store, app.state.worker
    set_responder(None)


def overdue_payment(store) -> str:
    """An open payment to-do, due before today, made from a mail from the payee."""
    with store.transaction() as tx:
        mail = tx.create(
            "source",
            {
                "received_at": "2026-01-02T09:00:00+00:00",
                "kind": "email",
                "title": "Your Acme Pay installment is due",
                "content_hash": "0" * 64,
                "trust": "untrusted",
            },
            _PM,
        ).id
        return tx.create(
            "action",
            {
                "text": "Pay the Acme Pay installment, $29.41, for the printer order (account ending 1234)",
                "owners": [{"person": OWNER}],
                "due": "2026-01-05",
                "source": mail,
                "notes": "From the Acme Pay mail 'Your Acme Pay installment is due'.",
            },
            _PM,
        ).id


def answering(ops: list[dict], summary: str = "Done."):
    set_responder(lambda task: json.dumps({"summary": summary, "ops": ops}))


def hand_over(client, worker, action: str, note: str | None = None) -> str:
    made = client.post(f"/api/actions/{action}/hand-over", json={"note": note} if note else {}).json()["request"]
    worker.run_pending()
    return made


def the_answer(text: str = "Done.") -> dict:
    return {"op": "answer", "text": text, "cites": [{"quote": "should not be to dos"}]}


def test_a_rule_name_written_as_words_does_not_make_the_whole_answer_unreadable(api):
    # The recorded real answer named its rule in words with a colon; that used to make the answer unreadable after the
    # second try, so nothing in it applied. The name is now made into its short form.
    client, store, worker = api
    action = overdue_payment(store)
    answering(RECORDED["ops"], RECORDED["summary"])
    hand_over(client, worker, action, WORDS)
    (rule,) = store.read().list("rule")
    assert rule.data["name"] == "acme-pay-mail-reminders-not-to-dos"
    (turn,) = client.get(f"/api/records/action/{action}/conversation").json()["turns"]
    assert turn["answer"] and "standing rule" in turn["answer"]["text"]


def test_a_rule_that_names_a_kind_of_work_there_is_not_is_refused_and_never_kept(api):
    client, store, worker = api
    action = overdue_payment(store)
    ops = json.loads(json.dumps(RECORDED["ops"]))
    ops[1]["applies_to"] = {"task_kinds": ["mail-reading"]}
    answering(ops)
    hand_over(client, worker, action, WORDS)
    assert store.read().list("rule") == []
    (turn,) = client.get(f"/api/records/action/{action}/conversation").json()["turns"]
    assert "isn't a kind of work" in json.dumps(turn)


def test_the_payment_case_makes_a_rule_closes_the_todo_with_undo_and_drafts_nothing(api):
    client, store, worker = api
    action = overdue_payment(store)
    answering(
        [
            the_answer("Added the rule and closed this to-do."),
            {
                "op": "rule.add",
                "name": "acme-pay-mail",
                "text": "Mail from Acme Pay records a reminder on the schedule and is not made into a to-do.",
                "evidence": {"quote": "Any incoming Acme Pay mails should record reminders on the schedule"},
            },
            {
                "op": "action.close",
                "id": action,
                "evidence": {"quote": "are automatically paid so they should not be to dos"},
            },
        ]
    )
    hand_over(client, worker, action, WORDS)
    view = store.read()
    assert [r.data["status"] for r in view.list("rule")] == ["active"]
    assert view.get("action", action).data["status"] == "done"
    assert [r for r in view.list("request") if r.data["task"] == action_work.TASK] == []
    (turn,) = client.get(f"/api/records/action/{action}/conversation").json()["turns"]
    close = next(o for o in turn["ops"] if o["op"] == "action.close")
    undone = client.post(f"/api/changesets/{turn['changeset']}/undo", json={"ops": [close["index"]]})
    assert undone.status_code == 200
    assert store.read().get("action", action).data["status"] == "open"


def test_words_that_ask_for_writing_queue_the_drafting_request_with_the_words_as_its_note(api):
    client, store, worker = api
    action = overdue_payment(store)
    answering([the_answer("Asked for a draft."), {"op": "work.draft", "id": action, "note": "Three lines, friendly."}])
    hand_over(client, worker, action, "Write the reply to the printer, three lines, friendly")
    (work,) = [r for r in store.read().list("request") if r.data["task"] == action_work.TASK]
    assert work.data["about"] == {"kind": "action", "id": action}
    assert work.data["note"] == "Three lines, friendly." and work.data["origin"] == "pm"
    assert store.read().get("action", action).data["status"] == "open"


def test_a_draft_is_not_asked_for_twice_or_on_a_closed_to_do(api):
    client, store, worker = api
    action = overdue_payment(store)
    action_work.hand_over(store, action)
    answering([the_answer(), {"op": "work.draft", "id": action}])
    client.post(f"/api/records/action/{action}/conversation", json={"message": "Write it up"})
    worker.run_pending()
    assert len([r for r in store.read().list("request") if r.data["task"] == action_work.TASK]) == 1
    (turn,) = client.get(f"/api/records/action/{action}/conversation").json()["turns"]
    assert any(o["op"] == "work.draft" and o["status"] != "applied" for o in turn["ops"])


def test_a_rule_about_another_sender_leaves_an_unrelated_todo_alone(api):
    # The recorded real answer to words about one sender's mail, given on a to-do that has nothing to do with it: the
    # rule is made and the to-do stays open.
    client, store, worker = api
    with store.transaction() as tx:
        other = tx.create(
            "action", {"text": "Send the final interior file to the printer", "owners": [{"person": OWNER}]}, _PM
        ).id
    answering(RECORDED_2["ops"], RECORDED_2["summary"])
    hand_over(client, worker, other, WORDS)
    assert [r.data["status"] for r in store.read().list("rule")] == ["active"]
    assert store.read().get("action", other).data["status"] == "open"


def test_the_recorded_answer_on_the_payment_case_keeps_the_rule_closes_the_todo_with_undo_and_drafts_nothing(api):
    # A real model's answer to words stating a rule on an overdue payment to-do made from the payee's mail: a rule, the
    # to-do closed, one answer, no request for a draft.
    client, store, worker = api
    action = overdue_payment(store)
    recorded = json.loads(RECORDED_3.replace("ACT-7", action))
    answering(recorded["ops"], recorded["summary"])
    hand_over(client, worker, action, WORDS)
    view = store.read()
    (rule,) = view.list("rule")
    assert rule.data["status"] == "active" and "Acme Pay" in rule.data["text"]
    assert view.get("action", action).data["status"] == "done"
    assert [r for r in view.list("request") if r.data["task"] == action_work.TASK] == []
    (turn,) = client.get(f"/api/records/action/{action}/conversation").json()["turns"]
    assert turn["answer"] and "Acme Pay" in turn["answer"]["text"]
    close = next(o for o in turn["ops"] if o["op"] == "action.close")
    assert client.post(f"/api/changesets/{turn['changeset']}/undo", json={"ops": [close["index"]]}).status_code == 200
    assert store.read().get("action", action).data["status"] == "open"
