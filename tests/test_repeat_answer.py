"""The same answer twice (design 6.22): the learning request for an answer the person has now given twice to
questions of one kind about one project is told so and asked for the routing entry or rule they imply, once. A
different answer, a first answer, another project, an entry already waiting or active, and a declined one all leave
the request as it was. Names and ids come from the fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from engine import repeat_answer
from engine.applier import pick_owner
from engine.learn import learn_request
from engine.packet import build
from engine.storage import WriteContext
from tests import test_corrections
from tests.test_corrections import PROJECT, other_of
from tests.test_knowledge_records import apply, source

env = test_corrections.env

TODAY = date(2026, 10, 14)
_TEST = WriteContext(actor="pm", trust="trusted", op="test.repeat")


def held(store, cfg, text, project=PROJECT["id"]):
    """A to-do waiting for an owner in a project, and the question asking who."""
    op = {"op": "action.add", "text": text, "project": project, "evidence": {"quote": text}}
    cs_id, result = apply(store, cfg, [op], origin="input", trust="untrusted", source_id=source(store), raw=text)
    assert result == ["applied"]
    outcome = store.read().get("changeset", cs_id).data["ops"][0]
    return outcome["question"]


def answered(store, cfg, text, person, project=PROJECT["id"]):
    question = held(store, cfg, text, project)
    pick_owner(store, question, person)
    return question


def learning_packet(ws, store, cfg, question):
    signal = next(s for s in store.read().list("signal") if s.data["kind"] == "routed" and question in s.data["refs"])
    request = learn_request(store.read(), signal.id)
    assert request is not None
    return build(ws, store, cfg, request.id, TODAY).task.request


def test_the_second_same_answer_makes_the_request_ask_for_the_entry_the_first_does_not(env):
    ws, cfg, store = env
    ana = other_of(cfg)
    first = answered(store, cfg, "Confirm the proof slot with the printer", ana)
    assert "# The same answer again" not in learning_packet(ws, store, cfg, first)
    second = answered(store, cfg, "Confirm the plate date with the printer", ana)
    packet = learning_packet(ws, store, cfg, second)
    assert "# The same answer again" in packet and "routing entry or the standing rule" in packet
    assert "2 routing questions" in packet and PROJECT["name"] in packet
    assert "Pick an owner: Confirm the proof slot with the printer" in packet


def test_a_different_answer_or_another_project_or_kind_is_no_repeat(env):
    ws, cfg, store = env
    ana = other_of(cfg)
    bea = other_of(cfg, skip=(ana,))
    answered(store, cfg, "Confirm the proof slot with the printer", ana)
    different = answered(store, cfg, "Confirm the plate date with the printer", bea)
    assert repeat_answer.find(store.read(), different) is None
    with store.transaction() as tx:
        elsewhere = tx.create("project", {"name": "Some other project"}, _TEST).id
    other_project = answered(store, cfg, "Confirm the cover files with the printer", ana, elsewhere)
    assert repeat_answer.find(store.read(), other_project) is None
    assert repeat_answer.find(store.read(), "Q-9999") is None


@pytest.mark.parametrize("status", ["proposed", "active", "discarded"])
def test_an_entry_already_waiting_active_or_declined_for_the_project_is_not_offered_again(env, status):
    ws, cfg, store = env
    ana = other_of(cfg)
    answered(store, cfg, "Confirm the proof slot with the printer", ana)
    with store.transaction() as tx:
        tx.create(
            "routing_entry",
            {
                "text": "Printer questions go to the production lead.",
                "topic": "printer questions",
                "person": ana,
                "origin": "assistant",
                "trust": "trusted",
                "learned_at": "2026-10-01T09:00:00+00:00",
                "status": status,
                **({"kept_by": ana, "kept_at": "2026-10-02T09:00:00+00:00"} if status == "active" else {}),
                "applies_to": {"projects": [PROJECT["id"]]},
            },
            _TEST,
        )
    second = answered(store, cfg, "Confirm the plate date with the printer", ana)
    assert repeat_answer.find(store.read(), second) is None
    assert "# The same answer again" not in learning_packet(ws, store, cfg, second)


def test_an_entry_for_another_project_does_not_stop_the_offer(env):
    ws, cfg, store = env
    ana = other_of(cfg)
    answered(store, cfg, "Confirm the proof slot with the printer", ana)
    with store.transaction() as tx:
        elsewhere = tx.create("project", {"name": "Some other project"}, _TEST).id
        tx.create(
            "routing_entry",
            {
                "text": "Printer questions go to the production lead.",
                "topic": "printer questions",
                "person": ana,
                "origin": "assistant",
                "trust": "trusted",
                "learned_at": "2026-10-01T09:00:00+00:00",
                "status": "discarded",
                "applies_to": {"projects": [elsewhere]},
            },
            _TEST,
        )
    second = answered(store, cfg, "Confirm the plate date with the printer", ana)
    assert repeat_answer.find(store.read(), second) is not None
