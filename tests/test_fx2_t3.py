"""Fixes from bug hunt T3 that live on the server, proved on the worst-case workspace (`tests/e2e_worst_case.py`)."""

from __future__ import annotations

from datetime import date

import pytest
from starlette.testclient import TestClient

from api.app import create_app
from engine.gate_measures import COUNT_LIMIT
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


def team_named(store, name):
    return next(t for t in store.read().list("team") if t.data["name"] == name)


def edit_team(client, team, fields):
    return client.post(
        "/api/records/edit", json={"kind": "team", "id": team.id, "fields": fields, "read_version": team.version}
    )


# T3-05: a name with nothing in it but spaces is refused, for a team, an organization and a person.
def test_a_name_of_only_spaces_is_refused_on_a_team_an_organization_and_a_person(worst_app):
    client, store, _ = worst_app
    team = team_named(store, "Empty team")
    org = store.read().list("organization")[0]
    person = store.read().list("person")[0]
    for kind, record, field in (("team", team, "name"), ("organization", org, "name"), ("person", person, "full_name")):
        answer = client.post(
            "/api/records/edit",
            json={"kind": kind, "id": record.id, "fields": {field: "     "}, "read_version": record.version},
        )
        assert answer.status_code >= 400, kind
        assert store.read().get(kind, record.id).data[field] == record.data[field]


# T3-06: two teams never share a name.
def test_a_team_cannot_take_another_teams_name_and_says_which_name(worst_app):
    client, store, _ = worst_app
    team = team_named(store, "Delivery drivers")
    answer = edit_team(client, team, {"name": "Empty team"})
    assert answer.status_code == 409
    assert answer.json()["detail"] == "there is already a team called Empty team"
    assert store.read().get("team", team.id).data["name"] == "Delivery drivers"


# T3-07: one slip of a few digits does not skew the figures.
def test_a_count_past_what_one_list_holds_is_refused_in_plain_words(worst_app):
    client, _, _ = worst_app
    today = date.today().isoformat()
    answer = client.put(f"/api/quality/counts/{today}", json={"present": COUNT_LIMIT + 1, "missed": 1})
    assert answer.status_code == 409 and "can't hold more than" in answer.json()["detail"]
    assert client.put(f"/api/quality/counts/{today}", json={"present": COUNT_LIMIT, "missed": 1}).status_code == 200
    assert client.get("/api/quality").json()["counts"]["limit"] == COUNT_LIMIT


# T3-09: teams are listed, and a person is put on one and taken off it as one change with one Undo.
def test_teams_are_listed_and_people_are_put_on_and_taken_off_with_undo(worst_app):
    client, store, _ = worst_app
    empty = team_named(store, "Empty team")
    listed = {t["name"]: t for t in client.get("/api/teams").json()}
    assert listed["Empty team"]["people"] == [] and len(listed["Kitchen and front of house"]["people"]) == 3
    person = store.read().list("person")[-1].id
    added = client.post(f"/api/teams/{empty.id}/members/add", json={"person": person})
    assert added.status_code == 200
    assert store.read().get("team", empty.id).data["members"] == [person]
    assert client.post(f"/api/changesets/{added.json()['changeset']}/undo", json={}).status_code == 200
    assert store.read().get("team", empty.id).data["members"] == []
    client.post(f"/api/teams/{empty.id}/members/add", json={"person": person})
    removed = client.post(f"/api/teams/{empty.id}/members/remove", json={"person": person})
    assert removed.status_code == 200 and store.read().get("team", empty.id).data["members"] == []
    # A person whose own record names the team is on it, and taking them off clears that too.
    other = store.read().list("person")[-2]
    client.post(
        "/api/records/edit",
        json={"kind": "person", "id": other.id, "fields": {"team": empty.id}, "read_version": other.version},
    )
    assert other.id in {t["id"]: t for t in client.get("/api/teams").json()}[empty.id]["people"]
    assert client.post(f"/api/teams/{empty.id}/members/remove", json={"person": other.id}).status_code == 200
    assert store.read().get("person", other.id).data.get("team") is None


# T3-10: a retired or set-aside entry is brought back as the person's own Keep, and Undo puts it back as it was.
def test_a_retired_or_set_aside_entry_can_be_used_again_and_undone(worst_app):
    client, store, _ = worst_app
    view = store.read()
    retired_id = next(
        e["id"] for e in client.get("/api/knowledge").json() if e["status"] == "active" and e["kind"] == "lesson"
    )
    entry = client.get("/api/knowledge").json()
    version = next(e["version"] for e in entry if e["id"] == retired_id)
    assert client.post(f"/api/knowledge/{retired_id}/retire", json={"read_version": version}).status_code == 200
    now = {e["id"]: e for e in client.get("/api/knowledge").json()}
    assert now[retired_id]["status"] == "retired"
    back = client.post(f"/api/knowledge/{retired_id}/reuse", json={"read_version": now[retired_id]["version"]})
    assert back.status_code == 200
    now = {e["id"]: e for e in client.get("/api/knowledge").json()}
    assert now[retired_id]["status"] == "active"
    assert client.post(f"/api/changesets/{back.json()['changeset']}/undo", json={}).status_code == 200
    assert {e["id"]: e for e in client.get("/api/knowledge").json()}[retired_id]["status"] == "retired"
    # An entry that was set aside comes back too, with what was said against it cleared.
    discarded = next(s for s in view.list("lesson") if s.data["status"] == "discarded")
    used = client.post(f"/api/knowledge/{discarded.id}/reuse", json={"read_version": discarded.version})
    assert used.status_code == 200
    data = store.read().get("lesson", discarded.id).data
    assert data["status"] == "active" and data["discard_reason"] is None and data["kept_by"]
    # An entry already in use has nothing to bring back.
    again = client.post(
        f"/api/knowledge/{discarded.id}/reuse", json={"read_version": store.read().get("lesson", discarded.id).version}
    )
    assert again.status_code == 409


# T3-01 and T3-02: the second press, with the version it read, answers "changed since you looked" in plain words.
def test_a_stale_press_on_what_was_learned_is_look_again_never_an_id(worst_app):
    client, _, _ = worst_app
    entry = next(e for e in client.get("/api/knowledge").json() if e["status"] == "active" and e["kind"] == "lesson")
    assert (
        client.post(f"/api/knowledge/{entry['id']}/retire", json={"read_version": entry["version"]}).status_code == 200
    )
    second = client.post(f"/api/knowledge/{entry['id']}/retire", json={"read_version": entry["version"]})
    assert second.status_code == 409 and second.headers["X-Cockpit-Needs"] == "look-again"
    assert entry["id"] not in second.json()["detail"]
    current = {e["id"]: e for e in client.get("/api/knowledge").json()}[entry["id"]]
    refused = client.post(f"/api/knowledge/{entry['id']}/retire", json={"read_version": current["version"]})
    assert refused.status_code == 409 and entry["id"] not in refused.json()["detail"]


# T3-11: the number beside a person in People is the number their page counts.
def test_the_number_beside_a_person_is_the_number_their_page_counts(worst_app):
    client, _, cfg = worst_app
    me = cfg.workspace.user.person
    for person in client.get("/api/people").json():
        page = client.get(f"/api/record-pages/{person['id']}", params={"kind": "person"}).json()
        said = (
            len(page["open_actions"]) if person["id"] == me else len(page["open_actions"]) + len(page["open_questions"])
        )
        assert person["open_items"] == said, person["name"]
