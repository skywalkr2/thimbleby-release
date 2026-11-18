"""The read-back for a rule the person states (design 6.7): four lines worked out from the rule's target and the
records, a rule that contradicts one in force waiting for the person, and the three answers it can be given. Names and
ids come from the fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine import read_back as read_back_module
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.applier import Context, Inputs, apply_changeset, undo
from engine.catch_up import move_held_rules
from engine.dispatcher import process
from engine.intake import hand_in
from engine.names import People
from engine.ops import CHANGESET
from engine.records import Scope
from engine.storage import WriteContext
from engine.today_queue import queue
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

PROJECT = fixture_records(DEMO_B, "project")[0]["id"]
PERSON = fixture_records(DEMO_B, "person")[0]["id"]
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
_TEST = WriteContext(actor="pm", trust="trusted", op="test.read_back")
STATED = "From now on every action says who it is for."
OLD = "Every action names a project."


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"storage.backups.automatic": False})
    application = create_app(ws, cfg, "rb-token", ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(application, headers={"Authorization": "Bearer rb-token"}) as client:
        yield ws, cfg, application.state.store, client
    set_responder(None)


def state(store, cfg, ops, *, origin="pm"):
    """Apply ops as the person's own note does (a request of origin `pm`): the changeset and each op's outcome."""
    with store.transaction() as tx:
        request = tx.create(
            "request",
            {"task": "notes", "origin": origin, "state": "done", "created_at": NOW.isoformat()},
            _TEST,
        )
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request.id, None, "", "", "trusted"),
        actor="assistant",
    )
    cs = CHANGESET.validate_python({"ops": ops}, context={"op_models": store.plugins.ops})
    cs_id = apply_changeset(cs, [], ctx, run=None)
    return cs_id, store.read().get("changeset", cs_id).data["ops"]


def say(env, op):
    """The person states a rule in a note and the assistant reads it as `op`: the changeset and its one outcome."""
    ws, cfg, store, _ = env
    set_responder(lambda task: json.dumps({"summary": "Kept a rule.", "ops": [op]}))
    handed = hand_in(ws, store, note=op["text"], now=NOW)
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    (outcome,) = store.read().get("changeset", cs_id).data["ops"]
    return cs_id, outcome


def rule(text, **fields):
    return {"op": "rule.add", "text": text, **fields}


def active_rule(store, cfg, text, **fields) -> str:
    """A rule the person already has: the id of its record."""
    _, (outcome,) = state(store, cfg, [rule(text, **fields)])
    assert outcome["status"] == "applied", outcome
    return outcome["records"][0]["id"]


def lines(store, scope, constrains=None, **kw):
    return read_back_module.read_back(store, store.read(), Scope.model_validate(scope), constrains, **kw)


def test_applies_to_names_the_record_types_fields_projects_and_people(env):
    _, _, store, _ = env
    got = lines(store, {"records": ["action.owners"], "projects": [PROJECT], "people": [PERSON]})["applies"]
    assert got["everywhere"] is False
    assert [(t["kind"], t["field"]) for t in got["targets"]] == [("action", "owners")]
    assert [p["id"] for p in got["projects"]] == [PROJECT] and got["projects"][0]["name"]
    assert [p["id"] for p in got["people"]] == [PERSON]
    assert lines(store, {})["applies"]["everywhere"] is True


def test_doesnt_change_lists_the_nearest_neighbors_and_at_most_three(env):
    _, _, store, _ = env
    kinds = [n for n in lines(store, {"records": ["action.project"]})["unchanged"] if n["why"] == "field"]
    assert {n["kind"] for n in kinds} == {"fact", "event", "note"}  # not an internal record that has a `project` too
    assert all(n["field"] == "project" and n["kind_label"] for n in kinds)
    with store.transaction() as tx:
        for n in range(4):
            tx.create("project", {"name": f"Another project {n}"}, _TEST)
    scope = {"records": ["action.project"], "projects": [PROJECT], "task_kinds": ["notes"]}
    got = lines(store, scope)["unchanged"]
    assert len(got) == 3
    assert {n["why"] for n in got} == {"field", "project", "task_kind"}  # one of each in turn, not three of one kind
    assert all(n.get("id") != PROJECT for n in got)


def test_overlaps_names_each_active_rule_whose_target_meets_this_one(env):
    _, cfg, store, _ = env
    same = active_rule(store, cfg, "Actions name a person.", applies_to={"records": ["action.owners"]})
    wide = active_rule(store, cfg, "Actions are written plainly.", applies_to={"records": ["action"]})
    active_rule(store, cfg, "Questions are short.", applies_to={"records": ["question.title"]})
    active_rule(
        store, cfg, "Owners in another project.", applies_to={"records": ["action.owners"], "projects": ["PRJ-9"]}
    )
    retired = active_rule(store, cfg, "An old action rule.", applies_to={"records": ["action.owners"]})
    state(store, cfg, [{"op": "rule.retire", "id": retired}])
    got = lines(store, {"records": ["action.owners"], "projects": [PROJECT]})["overlaps"]
    assert {o["id"] for o in got} == {same, wide}
    assert {o["text"] for o in got} == {"Actions name a person.", "Actions are written plainly."}
    # A rule that names no record type meets only another like it, and a different filter value is not shared.
    assert lines(store, {"records": ["action"], "filter": {"status": "done"}})["overlaps"] != []
    assert (
        lines(store, {"records": ["action.owners"], "filter": {"status": "done"}}, exclude={same})["overlaps"][0]["id"]
        == wide
    )


def test_it_would_change_counts_the_open_records_the_target_matches(env):
    _, _, store, _ = env
    open_now = [a for a in store.read().list("action") if a.data["status"] not in ("done", "dropped")]
    everywhere = lines(store, {"records": ["action"]})
    assert everywhere["count"] == len(open_now) and everywhere["matches_nothing"] is False
    assert {i["id"] for i in everywhere["items"]} == {a.id for a in open_now}
    in_project = [a for a in open_now if a.data["project"] == PROJECT]
    assert lines(store, {"records": ["action"], "projects": [PROJECT]})["count"] == len(in_project)
    done = lines(store, {"records": ["action"], "filter": {"status": "done"}})
    assert done["count"] == 0  # a finished record is never counted


def test_a_rule_that_matches_nothing_now_is_flagged_and_one_with_no_record_is_not_counted(env):
    _, _, store, _ = env
    nothing = lines(store, {"records": ["action"], "filter": {"text": "no action says this"}})
    assert nothing["count"] == 0 and nothing["matches_nothing"] is True and nothing["items"] == []
    unknown = lines(store, {"records": ["no-such-kind.owner"]})  # a type nothing here defines matches nothing
    assert unknown["count"] == 0 and unknown["matches_nothing"] is True
    prose = lines(store, {})
    assert prose["count"] is None and prose["matches_nothing"] is False


def test_a_rule_stated_in_a_note_applies_at_once_with_its_read_back_and_undo(env):
    _, cfg, store, client = env
    existing = active_rule(store, cfg, OLD, applies_to={"records": ["action.project"]})
    cs_id, outcome = say(env, rule(STATED, applies_to={"records": ["action.project"], "projects": [PROJECT]}))
    assert outcome["status"] == "applied"
    back = outcome["read_back"]
    assert back["applies"]["targets"][0]["field"] == "project"
    assert [o["id"] for o in back["overlaps"]] == [existing]
    assert back["count"] >= 1 and back["unchanged"]
    shown = next(c for c in client.get("/api/changes").json() if c["changeset"] and c["changeset"]["id"] == cs_id)
    assert shown["changeset"]["ops"][0]["read_back"]["overlaps"][0]["text"] == OLD
    rule_id = outcome["records"][0]["id"]
    assert store.read().get("rule", rule_id).data["status"] == "active"
    assert undo(store, cs_id).restored == [0]
    assert store.read().get("rule", rule_id) is None or store.read().get("rule", rule_id).data["status"] != "active"


def test_a_rule_that_contradicts_one_in_force_waits_even_though_the_person_typed_it(env):
    ws, cfg, store, client = env
    existing = active_rule(store, cfg, OLD)
    cs_id, outcome = say(env, rule("Actions needn't name a project.", contradicts=[existing]))
    assert outcome["status"] == "held" and outcome["records"] == []
    assert [p["check"] for p in outcome["problems"]] == ["rule-contradiction"]
    assert "contradicts a rule you already have" in outcome["reason"]
    assert [r.id for r in store.read().list("rule") if r.data["status"] == "active"] == [existing]
    line = next(line for line in queue(ws, store, cfg, NOW) if line.kind == "held")
    assert line.held["ask"] == "contradiction" and line.held["against"] == [OLD] and line.held["record"] == existing
    # The held rule is the person's own question: the catch-up never turns it into a proposal.
    assert move_held_rules(store, cfg, NOW) == []
    assert outcome["read_back"]["overlaps"] != [] or outcome["read_back"]["applies"]["everywhere"]


def test_a_contradiction_named_by_name_or_naming_nothing_active_is_handled(env):
    _, cfg, store, _ = env
    existing = active_rule(store, cfg, OLD, name="names-a-project")
    _, (by_name,) = state(store, cfg, [rule("Actions needn't name a project.", contradicts=["names-a-project"])])
    assert by_name["status"] == "held"
    _, (unknown,) = state(store, cfg, [rule("Questions are short.", contradicts=["no-such-rule"])])
    assert unknown["status"] == "applied"  # nothing active is contradicted, so nothing waits
    state(store, cfg, [{"op": "rule.retire", "id": existing}])
    _, (gone,) = state(store, cfg, [rule("Actions needn't name a project either.", contradicts=[existing])])
    assert gone["status"] == "applied"


def held_pair(env, text="Actions needn't name a project.", existing=None):
    _, cfg, store, _ = env
    existing = existing or active_rule(store, cfg, OLD)
    cs_id, outcome = say(env, rule(text, contradicts=[existing]))
    assert outcome["status"] == "held"
    return cs_id, existing


def answer(client, cs_id, body):
    done = client.post(f"/api/changesets/{cs_id}/ops/0/rule-answer", json=body)
    assert done.status_code == 200, done.text
    return done.json()


def statuses(store):
    return {r.data["text"]: r.data["status"] for r in store.read().list("rule")}


def test_the_new_rule_wins_the_old_one_is_retired_and_undo_takes_both_back(env):
    _, _, store, client = env
    cs_id, existing = held_pair(env)
    done = answer(client, cs_id, {"choice": "new"})
    assert statuses(store) == {OLD: "retired", "Actions needn't name a project.": "active"}
    assert done["retired"]
    # Undo: the new rule leaves, and the change that retired the old one is undone with it.
    assert client.post(f"/api/changesets/{cs_id}/ops/0/unrelease").status_code == 200
    assert client.post(f"/api/changesets/{done['retired']}/undo", json={}).status_code == 200
    assert store.read().get("rule", existing).data["status"] == "active"
    assert "active" not in [v for t, v in statuses(store).items() if t != OLD]


def test_the_existing_rule_wins_the_new_one_is_not_kept(env):
    _, _, store, client = env
    cs_id, existing = held_pair(env)
    assert answer(client, cs_id, {"choice": "existing"})["retired"] is None
    assert statuses(store) == {OLD: "active"}
    (outcome,) = store.read().get("changeset", cs_id).data["ops"]
    assert outcome["status"] == "undone"


def test_both_stay_and_the_new_one_can_be_narrowed_first(env):
    _, _, store, client = env
    cs_id, existing = held_pair(env)
    narrower = {"scope": "projects", "projects": [PROJECT]}
    answer(client, cs_id, {"choice": "both", "applies_to": narrower})
    assert statuses(store) == {OLD: "active", "Actions needn't name a project.": "active"}
    kept = next(r for r in store.read().list("rule") if r.id != existing)
    assert kept.data["applies_to"]["projects"] == [PROJECT]
    other_cs, _ = held_pair(env, "Actions needn't name a project at all.", existing)
    answer(client, other_cs, {"choice": "both"})
    assert len([r for r in store.read().list("rule") if r.data["status"] == "active"]) == 3


def test_narrowing_the_new_rule_limits_its_projects_and_keeps_the_rest_of_its_target(env):
    _, cfg, store, client = env
    existing = active_rule(store, cfg, OLD)
    cs_id, outcome = say(
        env, rule("Actions needn't name a project.", applies_to={"records": ["action.project"]}, contradicts=[existing])
    )
    assert outcome["status"] == "held"
    answer(client, cs_id, {"choice": "both", "applies_to": {"scope": "projects", "projects": [PROJECT]}})
    kept = next(r for r in store.read().list("rule") if r.id != existing)
    assert kept.data["applies_to"]["records"] == ["action.project"]
    assert kept.data["applies_to"]["scope"] == "projects" and kept.data["applies_to"]["projects"] == [PROJECT]


def test_an_answer_for_something_not_waiting_is_refused(env):
    _, cfg, store, client = env
    cs_id, (outcome,) = state(store, cfg, [rule("Questions are short.")])
    assert outcome["status"] == "applied"
    refused = client.post(f"/api/changesets/{cs_id}/ops/0/rule-answer", json={"choice": "new"})
    assert refused.status_code == 409


def test_the_golden_case_for_a_contradicting_rule_passes_and_fails_when_it_isnt_held(monkeypatch):
    """The evaluation case holds the contradiction (the check is the assistant naming the rule, then the applier
    holding it); an answer that leaves `contradicts` out applies the rule at once, which the case does not allow."""
    from tests.test_evaluate_harness import case_of, run_edited

    case_id = "a-stated-rule-that-contradicts-a-rule-in-force-waits"
    assert run_edited(monkeypatch, DEMO_B, case_id).passed
    case = case_of(DEMO_B, case_id)
    (rule_op,) = case["stub_answer"]["ops"]
    silent = {**case["stub_answer"], "ops": [{k: v for k, v in rule_op.items() if k != "contradicts"}]}
    assert not run_edited(monkeypatch, DEMO_B, case_id, stub_answer=silent).passed
