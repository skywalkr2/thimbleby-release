# ruff: noqa: F811
"""Mark sent on a copied follow-up marks what the copied message held, and nothing that came after (design 6.10, 6.35).

The person copies a message, sends it in their own mail program, and comes back to say so. In between, the assistant
may have added a question for the same person, or changed one the message held. What arrived after the copy never went
out, so it stays to send. What changed after the copy is put to the person: did it go as copied? Neither is an edit the
person made to the draft, so neither teaches the assistant anything about its wording.

The screen's path is followed through the API: read the follow-ups (what the screen shows and copies), then mark sent
with what that message held. Names and ids come from the fixtures."""

from __future__ import annotations

from typing import Any

from engine.followups import Held, mark_sent, sections
from tests.test_sent_version import (  # noqa: F401  (the fixtures)
    _TEST,
    EDITOR,
    NOW,
    api,
    copies,
    edited_signals,
    env,
)

WHO = EDITOR["id"]
LATER = "Which paper stock does the insert use?"


def shown(api) -> dict[str, Any]:
    """The editor's follow-up as the screen has it."""
    return next(s for s in api.get("/api/followups").json() if s["person"] == WHO)


def copied(section: dict[str, Any]) -> dict[str, Any]:
    """What the screen keeps when the person copies the message: each item to send with its version, and the words."""
    return {
        "questions": [{"id": q["id"], "version": q["version"]} for q in section["questions"] if q["status"] == "open"],
        "actions": [{"id": a["id"], "version": a["version"]} for a in section["actions"] if a["to_send"]],
        "message": section["message"],
    }


def add_question(store, title: str = LATER) -> str:
    with store.transaction() as tx:
        return tx.create("question", {"to": WHO, "title": title, "text": f"About: {title}"}, _TEST).id


def reword(store, question_id: str, title: str) -> None:
    with store.transaction() as tx:
        found = tx.get("question", question_id)
        tx.update("question", question_id, {"title": title}, _TEST, read_version=found.version)


def status_of(store, question_id: str) -> str:
    return store.read().get("question", question_id).data["status"]


def mark(api, section: dict[str, Any], held: dict[str, Any], **more: Any) -> dict[str, Any]:
    sent = api.post(f"/api/followups/{WHO}/mark-sent", json={"text": section["message"], "held": {**held, **more}})
    assert sent.status_code == 200, sent.text
    return sent.json()


def test_an_item_that_arrived_after_the_copy_stays_to_send_and_teaches_nothing(api):
    before = shown(api)
    held = copied(before)
    assert held["questions"], "the fixture gives the editor questions to send"
    late = add_question(api.store)  # the assistant adds one while the person is in their mail program
    assert shown(api)["message"] != before["message"]  # the draft on screen has moved on; what was sent has not

    counts = mark(api, before, held)

    assert sorted(counts["question_ids"]) == sorted(q["id"] for q in held["questions"])
    assert late not in counts["question_ids"] and status_of(api.store, late) == "open"
    assert counts["arrived"] == 1 and counts["changed"] == []
    assert edited_signals(api.store) == []  # the person changed nothing: no lesson about the draft's wording
    (kept,) = copies(api.store)
    assert kept.data["text"] == before["message"] and late not in kept.data["questions"]
    assert [q["id"] for q in shown(api)["questions"] if q["status"] == "open"] == [late]  # still there to send


def test_an_item_that_changed_after_the_copy_is_put_to_the_person_not_marked_and_not_learned_from(api):
    before = shown(api)
    held = copied(before)
    changed, *rest = [q["id"] for q in held["questions"]]
    reword(api.store, changed, "Which proof is the final one, the second or the third?")

    counts = mark(api, before, held)

    assert counts["changed"] == [
        {"kind": "question", "id": changed, "text": "Which proof is the final one, the second or the third?"}
    ]
    assert changed not in counts["question_ids"] and status_of(api.store, changed) == "open"
    assert sorted(counts["question_ids"]) == sorted(rest) and all(status_of(api.store, q) == "sent" for q in rest)
    assert edited_signals(api.store) == []

    # The person's answer: it went as I copied it. It joins the same message's copy; there is still nothing learned.
    answer = mark(api, before, {"questions": [{"id": changed, "version": 0}], "actions": []}, as_copied=True)
    assert answer["question_ids"] == [changed] and answer["changed"] == [] and status_of(api.store, changed) == "sent"
    assert edited_signals(api.store) == []
    (kept,) = copies(api.store)
    assert sorted(kept.data["questions"]) == sorted([changed, *rest])

    # Undo of that answer reopens only that item, and the copy stops covering it.
    undone = api.post(f"/api/followups/{WHO}/unmark-sent", json={"question_ids": [changed], "action_ids": []})
    assert undone.status_code == 200 and status_of(api.store, changed) == "open"
    assert all(status_of(api.store, q) == "sent" for q in rest)
    (kept,) = copies(api.store)
    assert sorted(kept.data["questions"]) == sorted(rest)


def test_an_edit_the_person_made_is_still_learned_from_when_something_arrived_since(api):
    before = shown(api)
    held = copied(before)
    add_question(api.store)
    own = before["message"] + "\n\nThanks for turning these around before Friday."
    sent = api.post(f"/api/followups/{WHO}/mark-sent", json={"text": own, "held": held})
    assert sent.status_code == 200
    (signal,) = edited_signals(api.store)
    assert signal.data["note"] == own  # measured against the message as it was copied


def test_without_what_the_message_held_everything_to_send_now_is_marked(env):
    _, cfg, store = env
    section = next(s for s in sections(store, cfg, NOW.date()) if s.person == WHO)
    to_send = [q["id"] for q in section.questions if q["status"] == "open"]
    counts = mark_sent(store, cfg, WHO, sent_text=section.message, now=NOW)
    assert sorted(counts["question_ids"]) == sorted(to_send) and counts["arrived"] == 0 and counts["changed"] == []


def test_an_item_the_message_held_that_is_gone_since_is_passed_over(env):
    _, cfg, store = env
    section = next(s for s in sections(store, cfg, NOW.date()) if s.person == WHO)
    held = Held(questions={**{q["id"]: q["version"] for q in section.questions}, "Q-GONE": 1}, message=section.message)
    counts = mark_sent(store, cfg, WHO, sent_text=section.message, now=NOW, held=held)
    assert "Q-GONE" not in counts["question_ids"] and counts["changed"] == [] and counts["questions"] > 0
