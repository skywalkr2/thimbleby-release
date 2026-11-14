"""A correction reaches every open item it covers (design 6.22): the request for a correction carries, after the
corrected item, the other open questions, to-dos and drafts for the same person, the same project or the same source,
newest first and at most `knowledge.correction_reach_items`; closed and unrelated items are left out, and the number is
a setting. Names and ids come from the fixtures."""

from __future__ import annotations

import json
import re
from datetime import date

from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.correction_reach import reach
from engine.corrections import request_change
from engine.dispatcher import process
from engine.packet import build
from engine.storage import WriteContext
from tests import test_corrections
from tests.test_corrections import PROJECT, other_of

env = test_corrections.env  # the corrections tests' workspace fixture

TODAY = date(2026, 10, 14)
_TEST = WriteContext(actor="pm", trust="trusted", op="test.reach")


def question(tx, to, title, **more):
    return tx.create("question", {"to": to, "title": title, "projects": [], **more}, _TEST).id


def make(store, cfg):
    """One question to a person, then others: two more to the same person (one answered), one to someone else in the
    same project, one from the same source, one unrelated, and a draft to the same person."""
    ana = other_of(cfg)
    bea = other_of(cfg, skip=(ana,))
    with store.transaction() as tx:
        first = question(tx, ana, "Is the cover final?", projects=[PROJECT["id"]], source="SRC-1")
        same_person = question(tx, ana, "Is the spine final?")
        answered = question(tx, ana, "Is the back final?", status="answered")
        same_project = question(tx, bea, "Is the layout final?", projects=[PROJECT["id"]])
        same_source = question(tx, bea, "Is the blurb final?", source="SRC-1")
        unrelated = question(tx, bea, "Is the index final?")
        action = tx.create(
            "action", {"text": "Send the cover files", "owners": [{"person": ana}], "status": "open"}, _TEST
        ).id
        done = tx.create("action", {"text": "Sent earlier", "owners": [{"person": ana}], "status": "done"}, _TEST).id
        draft = tx.create(
            "act",
            {
                "channel": "copy",
                "target": {"kind": "message", "recipients": [{"person": ana, "address": "ana@example.com"}]},
                "parts": {"body": "Hello about the cover"},
                "status": "draft",
            },
            _TEST,
        ).id
    return {
        "first": first,
        "same_person": same_person,
        "answered": answered,
        "same_project": same_project,
        "same_source": same_source,
        "unrelated": unrelated,
        "action": action,
        "done": done,
        "draft": draft,
    }


def test_the_others_for_the_same_person_project_or_source_come_newest_first_and_nothing_else(env):
    _, cfg, store = env
    made = make(store, cfg)
    found = reach(store, "question", made["first"], 20)
    ids = [i for _, i in found]
    mine = set(made.values())
    assert {i for i in ids if i in mine} == {
        made[k] for k in ("same_person", "same_project", "same_source", "action", "draft")
    }
    assert ids == sorted(ids, key=lambda i: int(re.search(r"(\d+)$", i).group(1)), reverse=True)
    assert (made["answered"] not in ids) and (made["done"] not in ids) and (made["unrelated"] not in ids)
    assert ("question", made["first"]) not in found


def test_the_limit_keeps_the_newest_and_zero_shows_none(env):
    _, cfg, store = env
    made = make(store, cfg)
    assert len(reach(store, "question", made["first"], 2)) == 2
    newest = reach(store, "question", made["first"], 20)[:2]
    assert reach(store, "question", made["first"], 2) == newest
    assert reach(store, "question", made["first"], 0) == []


def test_a_kind_of_item_whose_correction_states_no_rule_and_a_missing_item_reach_nothing(env):
    _, cfg, store = env
    make(store, cfg)
    assert reach(store, "fact", "FACT-1", 20) == []
    assert reach(store, "question", "Q-9999", 20) == []


def test_the_request_for_a_correction_carries_them_after_the_item_and_the_limit_is_a_setting(env):
    ws, cfg, store = env
    made = make(store, cfg)
    request, _ = request_change(ws, store, cfg, "question", made["first"], "All of these go to the editor instead")
    packet = build(ws, store, cfg, request, TODAY).task.request
    assert packet.index("Is the cover final?") < packet.index('source="reach"')
    block = packet[packet.index('source="reach"') :]
    for title in ("Is the spine final?", "Is the layout final?", "Is the blurb final?", "Send the cover files"):
        assert title in block
    assert "Hello about the cover" in block  # a draft is shown with its words
    assert "Is the back final?" not in block and "Is the index final?" not in block and "Sent earlier" not in block
    cfg.dispatch.knowledge.correction_reach_items = 0
    again = build(ws, store, cfg, request, TODAY).task.request
    assert 'source="reach"' not in again


def test_a_correction_with_nothing_else_open_for_it_adds_no_block(env):
    ws, cfg, store = env
    with store.transaction() as tx:
        stranger = tx.create("person", {"full_name": "Someone With Nothing Else Open"}, _TEST).id
        alone = question(tx, stranger, "Is the cover final?")
    request, _ = request_change(ws, store, cfg, "question", alone, "Ask the editor instead")
    assert 'source="reach"' not in build(ws, store, cfg, request, TODAY).task.request


def test_items_another_note_route_shows_are_not_a_corrections_reach(env):
    """Only "Change this" carries the others: a note typed while marking something done is about that one thing."""
    from engine.intake import note_as_input

    ws, cfg, store = env
    made = make(store, cfg)
    request = note_as_input(
        ws, store, cfg, item=("action", made["action"]), text="It went out on Monday, to everyone", route="mark_done"
    )
    assert 'source="reach"' not in build(ws, store, cfg, request, TODAY).task.request


def test_the_assistants_answer_that_changes_two_questions_is_one_change_naming_each_with_its_own_undo(env):
    from datetime import UTC, datetime

    from engine.dispatcher import undo_changeset

    ws, cfg, store = env
    made = make(store, cfg)
    note = "Not my job to ask them any of these"
    ops = [
        {"op": "question.drop", "id": made[k], "reason": note, "evidence": {"quote": note}}
        for k in ("first", "same_person")
    ]
    set_responder(lambda task: json.dumps({"summary": "Dropped both.", "ops": ops}))
    request, _ = request_change(ws, store, cfg, "question", made["first"], note)
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), request, now=now)
    outcomes = store.read().get("changeset", cs_id).data["ops"]
    assert [o["status"] for o in outcomes] == ["applied", "applied"], [o.get("problems") for o in outcomes]
    assert {o["op"]["id"] for o in outcomes} == {made["first"], made["same_person"]}
    assert {o["group"] for o in outcomes} == {"op0", "op1"}  # each is its own group, so each has its own Undo
    assert "Is the cover final?" in outcomes[0]["label"] and "Is the spine final?" in outcomes[1]["label"]
    assert store.read().get("question", made["unrelated"]).data["status"] == "open"
    undo_changeset(store, cs_id)
    assert store.read().get("question", made["same_person"]).data["status"] == "open"
