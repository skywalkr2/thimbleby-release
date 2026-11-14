"""Fixes from bug hunt H1 that live on the server, proved on the worst-case workspace (`tests/e2e_worst_case.py`)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from api.app import create_app
from engine.workspace import init_workspace
from tests import e2e_worst_case as worst
from tests.e2e_just_me import the_person

TOKEN = "t"


@pytest.fixture
def worst_app(tmp_path):
    ws = init_workspace(tmp_path / "ws", git=False, you=the_person())
    cfg = ws.config(env={}, flags={"steward.hold_outside_hours": False})
    app = create_app(ws, cfg, TOKEN, start_worker=False)
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
        made = worst.seed_sides(client)
        worst.seed_worst_case(ws, app.state.store, cfg, made["ids"])
        yield client, app.state.store, cfg
    finally:
        app.state.store.close()


# H1-03: a side's lines leaking into another side.
def test_a_held_review_is_on_the_side_of_the_to_do_it_is_about(worst_app):
    client, store, _ = worst_app
    view = store.read()
    lines = [line for line in client.get("/api/today/queue").json() if line["kind"] == "held"]
    assert lines
    for line in lines:
        action = view.get("action", line["held"]["record"])
        assert line["side"] == action.data["project"], line["key"]


def test_a_line_about_to_dos_on_several_sides_names_each_side_and_none_else(worst_app):
    client, store, _ = worst_app
    view = store.read()
    several = [
        line for line in client.get("/api/today/queue").json() if line["kind"] == "send" and len(line["actions"]) > 1
    ]
    assert several
    for line in several:
        on = {view.get("action", a).data["project"] for a in line["actions"]}
        assert len(on) > 1 and line["side"] is None
        assert set(line["sides"]) == on


# H1-02: something lost. Undo of "Close it" puts the review back.
def test_undo_of_a_yes_to_a_held_review_brings_the_review_back(worst_app):
    client, store, _ = worst_app

    def held_keys():
        return [line["key"] for line in client.get("/api/today/queue").json() if line["kind"] == "held"]

    before = held_keys()
    assert "held:CS-5:0" in before
    assert client.post("/api/changesets/CS-5/ops/0/release", json={"person": None}).status_code == 200
    assert "held:CS-5:0" not in held_keys()
    action = store.read().get("action", "ACT-64").data
    assert action["status"] != "open"
    report = client.post("/api/changesets/CS-5/ops/0/unrelease").json()
    assert report["restored"] == [0]
    assert store.read().get("action", "ACT-64").data["status"] == "open"
    assert held_keys() == before
    # And it can be answered again.
    assert client.post("/api/changesets/CS-5/ops/0/release", json={"person": None}).status_code == 200
    assert "held:CS-5:0" not in held_keys()


# H1-01: a refusal for "changed since it was read" is plain words, with the need the screen reads as "look again".
def test_a_conflict_is_plain_words_and_asks_to_look_again(worst_app, monkeypatch):
    import api.routes
    from engine.storage import ConflictError

    client, _, _ = worst_app

    def clash(*args, **kwargs):
        raise ConflictError("changeset", "CS-5", ["ops", "status"])

    monkeypatch.setattr(api.routes, "release", clash)
    answer = client.post("/api/changesets/CS-5/ops/0/release", json={"person": None})
    assert answer.status_code == 409
    assert answer.headers["X-Cockpit-Needs"] == "look-again"
    detail = answer.json()["detail"]
    for internal in ("CS-5", "changeset", "ops", "status"):
        assert internal not in detail


# H1-07: a to-do with no owner is a line on Today that asks "Pick an owner" (the seed makes the applier's question).
def test_every_to_do_with_no_owner_is_a_pick_an_owner_line_on_today(worst_app):
    client, store, _ = worst_app
    held = [a for a in store.read().list("action") if a.data["status"] == "held"]
    assert len(held) == 5
    lines = [line for line in client.get("/api/today/queue").json() if line["kind"] == "owner"]
    assert sorted(line["actions"][0] for line in lines) == sorted(a.id for a in held)


# H1-08 (the restart state): adding sides while the app runs asks for no restart, and no "restart" line is on Today.
def test_adding_sides_while_the_app_runs_asks_for_no_restart(tmp_path):
    ws = init_workspace(tmp_path / "ws", git=False, you=the_person())
    cfg = ws.config(env={}, flags={"steward.hold_outside_hours": False})
    app = create_app(ws, cfg, TOKEN, start_worker=False)
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
        worst.seed_sides(client)
        worker = app.state.worker
        assert worker._changed_since_start() is False
        assert worker.restart_needed is None and worker.restart_for == []
        assert [line for line in client.get("/api/today/queue").json() if line["kind"] == "restart"] == []
    finally:
        app.state.store.close()


# H1-10: the one reader of a day in words, which both the add box and the needs-a-date box ask, reads "next Tuesday".
def test_the_one_day_reader_reads_next_tuesday(worst_app):
    client, _, _ = worst_app
    said = client.post("/api/todos/day", json={"words": "next Tuesday"}).json()
    assert said["status"] == "ok" and said["day"]
