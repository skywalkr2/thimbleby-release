"""What a step makes can be named by the steps after it in the same answer (the #66 re-check, M-2), over the whole
family: every op that takes a project or person reference, with the referent made earlier in the same change. A new
project or person from an input waits for the person; every step that names
it waits with it, and comes in, with the new record's id, when the person says yes to it. Nothing is refused for naming
it."""

from __future__ import annotations

import json

import pytest

from engine import ops as op_models
from engine.applier import release
from engine.names import People
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_knowledge_records import apply, source

NOTE = (
    "Met with Rowan Pike about the Winter Fair, which opens on March 14 at 10am. Rowan will send the crate sizes by "
    "Friday. Rowan is away from March 2. Rowan's email is rowan@example.com. Ask Rowan about the stall plan. "
    "Planning meetings every Tuesday. A stall is a booth at the fair."
)
FAIR, ROWAN = "Winter " + "Fair", "Rowan " + "Pike"
NEW_PROJECT = {"op": "project.add", "name": FAIR, "evidence": {"quote": "the Winter Fair"}}
NEW_PERSON = {"op": "person.add", "full_name": ROWAN}
PLAN = "https" + "://example.com/stall-plan"


def project_samples(me: str) -> dict[str, dict]:
    """A step of each kind that names the project made by step 0."""
    return {
        "note": {"op": "note", "text": "Planning for the fair has started.", "project": "$new:0"},
        "fact": {
            "op": "fact",
            "text": "The fair opens on March 14.",
            "project": "$new:0",
            "evidence": {"quote": "opens on March 14"},
        },
        "event.add": {
            "op": "event.add",
            "title": "The fair opens",
            "start": "2027-03-14T10:00:00+00:00",
            "project": "$new:0",
            "evidence": {"quote": "opens on March 14 at 10am"},
        },
        "series.add": {
            "op": "series.add",
            "title": "Fair planning",
            "repeats": "every Tuesday",
            "project": "$new:0",
            "evidence": {"quote": "Planning meetings every Tuesday"},
        },
        "action.add": {
            "op": "action.add",
            "text": "Send the crate sizes",
            "owners": [me],
            "project": "$new:0",
            "evidence": {"quote": "will send the crate sizes by Friday"},
        },
        "question.add": {
            "op": "question.add",
            "to": me,
            "title": "What is the stall plan?",
            "text": "What is the stall plan?",
            "project": "$new:0",
        },
        "record.log": {"op": "record.log", "project": "$new:0", "text": "Met about the fair."},
        "project.role": {
            "op": "project.role",
            "project": "$new:0",
            "person": me,
            "role": "run",
            "evidence": {"quote": "Met with Rowan Pike about the Winter Fair"},
        },
        "glossary.add": {
            "op": "glossary.add",
            "term": "stall",
            "meaning": "a booth at the fair",
            "text": "A stall is a booth at the fair.",
            "project": "$new:0",
        },
    }


def person_samples(open_action: str = "ACT-0") -> dict[str, dict]:
    """A step of each kind that names the person made by step 0: by name where the op takes names, else by "$new:0"."""
    return {
        "action.owners": {
            "op": "action.owners",
            "id": open_action,
            "owners": [ROWAN],
            "evidence": {"quote": "Rowan will send the crate sizes by Friday"},
        },
        "action.add": {
            "op": "action.add",
            "text": "Send the crate sizes",
            "owners": [ROWAN],
            "evidence": {"quote": "Rowan will send the crate sizes by Friday"},
        },
        "question.add": {
            "op": "question.add",
            "to": "$new:0",
            "title": "What is the stall plan?",
            "text": "What is the stall plan?",
            "links": [{"label": "The stall plan", "url": PLAN}],
            "asks_about": "design",
            "matters_for": "the fair's stall layout",
        },
        "person.contact": {
            "op": "person.contact",
            "person": "$new:0",
            "kind": "email",
            "value": "rowan@example.com",
            "evidence": {"quote": "rowan@example.com"},
        },
        "person.away": {
            "op": "person.away",
            "person": "$new:0",
            "start": "2027-03-02",
            "evidence": {"quote": "Rowan is away from March 2"},
        },
        "routing.add": {
            "op": "routing.add",
            "person": "$new:0",
            "topic": "crates",
            "text": "Rowan handles the crates.",
        },
    }


#: Ops with a project or person reference that no answer to an input names a new record with, and why.
NOT_FROM_AN_ANSWER = {
    "act.draft": "a draft's recipient is read by its channel, which takes only people on file",
    "file.add": "a file is the person's own upload, never an answer's step",
    "glossary.update": "it changes a term on file; a new project's terms are added with glossary.add",
    "event.guests": "it changes the guests of an entry on file, by the names an input gives",
    "question.move": "it moves a question on file to someone on file",
    "away.read": "it reads an away entry of a calendar on file",
    "person.offer": "the person's own choice on a person on file",
    "source.limit": "the person's own setting for a source on file",
    "source.widen": "the person's own setting for a source on file",
    "person.forget": "forgetting is the person's own act on someone on file",
    "stage.move": "its reference is a stage's name, not a person",
    "list.rename": "its reference is a list's name, not a person",
}


def family(fields: tuple[str, ...]) -> set[str]:
    found = set()
    for model in vars(op_models).values():
        is_op = isinstance(model, type) and issubclass(model, op_models.OpModel) and "op" in model.model_fields
        if is_op and any(f in model.model_fields for f in fields):
            found.add(str(model.model_fields["op"].annotation).split("[", 1)[-1].strip("'\"]"))
    return found


def test_every_op_that_names_a_project_or_a_person_is_covered_or_excluded_with_its_reason():
    projects = family(("project",))
    people = family(("person", "owners", "people", "to", "from_person"))
    assert projects <= set(project_samples("PER-0")) | set(NOT_FROM_AN_ANSWER), projects - set(project_samples("PER-0"))
    assert people <= set(person_samples()) | {"project.role"} | set(NOT_FROM_AN_ANSWER), people - set(person_samples())


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


#: Steps that wait for a yes of their own whatever they name: a role on a project, and a way to reach someone.
OWN_YES = {"project.role", "person.contact"}


def came_in(store, cfg, cs_id: str, own_yes: set[str] = OWN_YES) -> dict:
    """Say yes to step 0: step 1 comes in with it, unless it waits for a yes of its own, which is then given. Step 1 as
    it was applied."""
    release(store, cfg, cs_id, 0)
    step = store.read().get("changeset", cs_id).data["ops"][1]
    if step["op"]["op"] not in own_yes:
        assert step["status"] == "applied", (step["op"]["op"], step.get("reason"))
    elif step["status"] == "held":
        assert not (step.get("reason") or "").startswith("Comes in with"), step.get("reason")
        release(store, cfg, cs_id, 1)
        step = store.read().get("changeset", cs_id).data["ops"][1]
    return step


@pytest.mark.parametrize("kind", sorted(project_samples("PER-0")))
def test_a_step_that_names_a_new_project_waits_with_it_and_comes_in_on_it(env, kind):
    ws, cfg, store = env
    sample = project_samples(People(store, cfg).pm)[kind]
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, done = apply(store, cfg, [NEW_PROJECT, sample], **given)
    assert done == ["held", "held"], (kind, done)
    step = came_in(store, cfg, cs)
    made = store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]
    assert step["status"] == "applied", (kind, step.get("reason"))
    assert "$new:" not in json.dumps(step["op"]) and made in json.dumps(step["op"]), kind


@pytest.mark.parametrize("kind", sorted(person_samples()))
def test_a_step_that_names_a_new_person_waits_with_them_and_comes_in_with_them(env, kind):
    ws, cfg, store = env
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    open_action = next(a.id for a in store.read().list("action") if a.data["status"] == "open")
    cs, done = apply(store, cfg, [NEW_PERSON, person_samples(open_action)[kind]], **given)
    assert done == ["held", "held"], (kind, done)
    # A question to someone else answers to its own checks too (what its answer would change, a link they can open).
    step = came_in(store, cfg, cs, OWN_YES | {"question.add"})
    made = store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]
    assert step["status"] == "applied", (kind, step.get("reason"))
    assert "$new:" not in json.dumps(step["op"]), kind
    # The step names the person by id, or by name where the op takes names: either way what it wrote is theirs.
    written = [store.read().get(r["kind"], r["id"]).data for r in step["records"] if r.get("kind") != "person"]
    assert made in json.dumps(step["op"]) or any(made in json.dumps(w) for w in written), (kind, written)


def test_keeping_a_new_project_as_it_was_takes_the_steps_that_named_it_with_it(env):
    from engine.applier import decline_held

    ws, cfg, store = env
    me = People(store, cfg).pm
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, _ = apply(store, cfg, [NEW_PROJECT, project_samples(me)["event.add"]], **given)
    decline_held(store, cs, 0)
    assert [o["status"] for o in store.read().get("changeset", cs).data["ops"]] == ["undone", "undone"]


def test_no_to_a_new_person_leaves_nothing_of_theirs_waiting_for_ever(env):
    """The #67 re-check (N-9): after "no" to a new person, the to-do they would own and a question to them stayed
    waiting for ever. The question goes with the person; the to-do comes in without them, waiting for "Pick an
    owner"; its "who is this?" question is answered by the "no"."""
    from engine.applier import decline_held

    ws, cfg, store = env
    samples = person_samples()
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, done = apply(store, cfg, [NEW_PERSON, samples["action.add"], samples["question.add"]], **given)
    assert done == ["held", "held", "held"]
    decline_held(store, cs, 0)
    ops = store.read().get("changeset", cs).data["ops"]
    assert [o["status"] for o in ops] == ["undone", "applied", "undone"], [(o["status"], o.get("reason")) for o in ops]
    action = store.read().get("action", ops[1]["records"][0]["id"]).data
    assert action["owners"] == [] and action["status"] == "held"  # waiting for "Pick an owner"
    open_who_is = [
        q
        for q in store.read().list("question")
        if q.data["status"] == "open" and (q.data.get("resolves") or {}).get("kind") == "held-op"
    ]
    assert open_who_is == []
