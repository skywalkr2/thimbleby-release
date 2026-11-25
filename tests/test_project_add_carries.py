"""A project the assistant proposes carries what the same note says about it (the #66 re-check, M-2): its target day and
who runs it ride on the proposal itself, since nothing else in the answer can name a project that has no id yet. The
person's yes brings them in with the project; a made-up reference to it is sent back with what to do instead."""

from __future__ import annotations

from datetime import date

import pytest

from engine.applier import release
from engine.names import People
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_knowledge_records import apply, reasons, source

NOTE = "The Winter Fair opens on March 14, and I'm running it."
NAME = "Winter " + "Fair"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def proposal(me: str) -> dict:
    return {
        "op": "project.add",
        "name": NAME,
        "target": "2027-03-14",
        "roles": [{"person": me, "role": "run"}],
        "evidence": {"quote": "The Winter Fair opens on March 14, and I'm running it"},
    }


def test_a_proposed_project_keeps_its_target_day_and_its_runner_when_the_person_says_yes(env):
    ws, cfg, store = env
    me = People(store, cfg).pm
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, done = apply(store, cfg, [proposal(me)], **given)
    assert done == ["held"]
    assert not any(p.data["name"] == NAME for p in store.read().list("project"))
    release(store, cfg, cs, 0)
    (made,) = [p for p in store.read().list("project") if p.data["name"] == NAME]
    assert date.fromisoformat(str(made.data["target"])) == date(2027, 3, 14)
    assert made.data["roles"] == [{"person": me, "role": "run"}]


def test_a_role_for_someone_unknown_is_refused_with_the_reason(env):
    ws, cfg, store = env
    op = {**proposal("Someone Nobody Knows"), "roles": [{"person": "Someone Nobody Knows", "role": "watch"}]}
    cs, done = apply(store, cfg, [op], origin="pm", confirmed=True, raw=NOTE)
    assert done == ["refused"] and "isn't one known person" in (reasons(store, cs)[0] or "")


def test_a_made_up_reference_to_a_proposed_project_is_sent_back_saying_what_to_do(env):
    """The reviewer's case: the model named the project it proposed "@project.add:1" in the ops after it."""
    ws, cfg, store = env
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    ops = [
        {"op": "project.add", "name": NAME, "evidence": {"quote": "The Winter Fair"}},
        {
            "op": "fact",
            "text": "The Winter Fair opens on March 14.",
            "project": "@project.add:0",
            "evidence": {"quote": "opens on March 14"},
        },
    ]
    cs, done = apply(store, cfg, ops, **given)
    why = reasons(store, cs)[1] or ""
    assert done[1] == "refused"
    assert "has no id yet" in why and '"project.add" itself' in why


def test_a_project_from_the_persons_own_note_names_the_organization_the_note_names(tmp_path):
    """The first-week journey (J-3): "Dana Ortiz is my manager at <employer>... I'm running two projects" held the
    projects on "only you can say". The person's own note says it; outside content still waits for them."""
    from engine.storage import Store
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B
    from tests.test_knowledge_records import apply, source

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    try:
        employer = "Harborline " + "Museum"
        said = f"My manager at {employer} asked me to run the Winter Fair."
        side = {"op": "project.add", "name": employer, "organization": employer, "evidence": {"quote": said}}
        fair = {"op": "project.add", "name": "Winter " + "Fair", "parent": "$new:0", "evidence": {"quote": said}}
        mine = source(store, trust="trusted")
        cs, done = apply(store, cfg, [side, fair], origin="pm", trust="trusted", source_id=mine, raw=said)
        assert done == ["applied", "applied"]
        ops = store.read().get("changeset", cs).data["ops"]
        side_id, fair_id = (o["records"][0]["id"] for o in ops)
        org = store.read().get("project", side_id).data["organization"]
        assert store.read().get("organization", org).data["name"] == employer
        assert store.read().get("project", fair_id).data["parent"] == side_id
        outside = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": said}
        _, done = apply(
            store, cfg, [{**side, "name": "Quayside " + "Gallery", "organization": "Quayside " + "Gallery"}], **outside
        )
        assert done == ["held"]
    finally:
        store.close()


def test_a_project_inside_a_new_side_from_outside_content_comes_in_under_the_side_when_it_is_released(tmp_path):
    """`$new:<n>` names the record of the step's own kind: a side made with its organization is the project, not the
    organization it made first, both when applied and when released."""
    from engine.applier import release
    from engine.storage import Store
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B
    from tests.test_knowledge_records import apply, source

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    try:
        employer = "Quayside " + "Gallery"
        said = f"At {employer} we are starting the Lantern Walk."
        side = {"op": "project.add", "name": employer, "organization": employer, "evidence": {"quote": said}}
        walk = {"op": "project.add", "name": "Lantern " + "Walk", "parent": "$new:0", "evidence": {"quote": said}}
        outside = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": said}
        cs, done = apply(store, cfg, [side, walk], **outside)
        assert done == ["held", "held"]
        release(store, cfg, cs, 0)
        ops = store.read().get("changeset", cs).data["ops"]
        if ops[1]["status"] == "held":
            release(store, cfg, cs, 1)
            ops = store.read().get("changeset", cs).data["ops"]
        side_id = next(r["id"] for r in ops[0]["records"] if r["kind"] == "project")
        walk_id = next(r["id"] for r in ops[1]["records"] if r["kind"] == "project")
        assert store.read().get("project", walk_id).data["parent"] == side_id
    finally:
        store.close()
