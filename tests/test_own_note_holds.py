"""A to-do the person's own note puts on hold is theirs and shows its hold (the #66 re-check, M-3): "Hold the gala
invitations until Dana approves the guest list" made a to-do with no owner, which the app files as "Pick an owner", not
as the person's own on hold. From outside content a to-do that names nobody still waits for an owner."""

from __future__ import annotations

import pytest

from engine.applier import release
from engine.names import People
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_knowledge_records import apply, source

NOTE = "Hold the fair invitations until the board approves the guest list."
HELD = {
    "op": "action.add",
    "text": "Send the fair invitations",
    "waiting_for": "the board approves the guest list",
    "evidence": {"quote": "Hold the fair invitations until the board approves the guest list"},
}


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def made(store, cs_id):
    record = store.read().get("changeset", cs_id).data["ops"][0]["records"][0]
    return store.read().get("action", record["id"]).data


def test_a_to_do_on_hold_from_the_persons_own_note_is_theirs_and_on_hold(env):
    ws, cfg, store = env
    cs, done = apply(
        store, cfg, [HELD], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=NOTE
    )
    action = made(store, cs)
    assert done == ["applied"]
    assert action["status"] == "open" and [o["person"] for o in action["owners"]] == [People(store, cfg).pm]
    assert action["on_hold"]["waiting_for"] == "the board approves the guest list"


def test_a_to_do_that_names_nobody_from_outside_content_still_waits_for_an_owner(env):
    ws, cfg, store = env
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, _ = apply(store, cfg, [HELD], **given)
    action = made(store, cs)
    assert action["status"] == "held" and action["owners"] == []


def test_a_hold_lifts_from_a_to_do_still_waiting_for_an_owner_which_keeps_waiting_for_one(env):
    """The first-week journey (J-1): a hold and a missing owner are separate states. The approval the hold waited for
    lifts it ("ACT-1 is waiting for an owner, not on hold" refused it), and the to-do still waits for an owner."""
    ws, cfg, store = env
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, _ = apply(store, cfg, [HELD], **given)
    action_id = store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]
    approved = "The board approved the guest list today."
    lift = {"op": "action.unhold", "id": action_id, "evidence": {"quote": approved}}
    mine = source(store, trust="trusted")
    _, done = apply(store, cfg, [lift], origin="pm", trust="trusted", source_id=mine, raw=approved)
    action = store.read().get("action", action_id).data
    assert done == ["applied"]
    assert action["on_hold"] is None and action["status"] == "held" and action["owners"] == []


def owner_question(store, action_id):
    return next(
        q
        for q in store.read().list("question")
        if (q.data.get("resolves") or {}).get("kind") == "owner" and q.data["resolves"].get("action") == action_id
    )


def someone_else(store, cfg):
    me = People(store, cfg).pm
    return next(p.data["full_name"] for p in store.read().list("person") if p.id != me and p.data.get("full_name"))


def waiting_for_an_owner(store, cfg):
    given = {"origin": "input", "trust": "untrusted", "source_id": source(store), "raw": NOTE}
    cs, _ = apply(store, cfg, [HELD], **given)
    return store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]


def test_saying_who_owes_a_to_do_gives_it_its_owners_and_answers_its_owner_question(env):
    """The first-week journey (J-2): no step could change a to-do's owner, so "the invitations are Dana's" was lost."""
    ws, cfg, store = env
    action_id = waiting_for_an_owner(store, cfg)
    name = someone_else(store, cfg)
    said = f"The fair invitations are {name}'s to send."
    step = {"op": "action.owners", "id": action_id, "owners": [name], "evidence": {"quote": said}}
    _, done = apply(
        store, cfg, [step], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=said
    )
    action = store.read().get("action", action_id).data
    person = People(store, cfg).resolve(name).person
    assert done == ["applied"]
    assert action["status"] == "open" and [o["person"] for o in action["owners"]] == [person]
    assert owner_question(store, action_id).data["status"] == "answered"


def test_an_owner_nobody_knows_waits_for_the_person_and_changes_nothing(env):
    ws, cfg, store = env
    action_id = waiting_for_an_owner(store, cfg)
    said = "The fair invitations are Quillon Varga's to send."
    step = {"op": "action.owners", "id": action_id, "owners": ["Quillon Varga"], "evidence": {"quote": said}}
    _, done = apply(
        store, cfg, [step], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=said
    )
    assert done != ["applied"]
    assert store.read().get("action", action_id).data["owners"] == []
    assert owner_question(store, action_id).data["status"] == "open"


def test_an_owner_question_never_closes_without_the_owner_being_given(env):
    """The first-week journey (J-7): closing "Pick an owner" without assigning anyone was a quiet loss."""
    ws, cfg, store = env
    action_id = waiting_for_an_owner(store, cfg)
    qid = owner_question(store, action_id).id
    said = "I'll sort out the invitations later."
    close = {"op": "question.done", "id": qid, "answer": "later", "evidence": {"quote": said}}
    _, done = apply(
        store, cfg, [close], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=said
    )
    assert done == ["refused"]
    assert owner_question(store, action_id).data["status"] == "open"


def test_a_change_of_owner_from_outside_content_waits_for_a_yes(env):
    """Only a change suggested by outside content waits; the person's own word applies at once."""
    ws, cfg, store = env
    me = People(store, cfg).pm
    open_action = next(
        a
        for a in store.read().list("action")
        if a.data["status"] == "open" and a.data["owners"][:1] == [{"person": me, "team": None}]
    )
    name = someone_else(store, cfg)
    said = f"This one is {name}'s to send now."
    step = {"op": "action.owners", "id": open_action.id, "owners": [name], "evidence": {"quote": said}}
    cs, done = apply(store, cfg, [step], origin="input", trust="untrusted", source_id=source(store), raw=said)
    assert done == ["held"]
    assert store.read().get("action", open_action.id).data["owners"] == open_action.data["owners"]
    release(store, cfg, cs, 0)
    owners = [o["person"] for o in store.read().get("action", open_action.id).data["owners"]]
    assert owners == [People(store, cfg).resolve(name).person]


def test_the_persons_own_correction_of_an_owner_teaches_the_next_to_do_like_it(env):
    """ "Correction: the fair invitations are <name>'s to send" applies at once, and the next similar to-do
    (the gala sponsor letters) should follow it: the correction is recorded with the person's words, naming the to-do
    and the change that made it, and the learning from it is queued at once."""
    ws, cfg, store = env
    cs, _ = apply(store, cfg, [HELD], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=NOTE)
    action_id = store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]
    name = someone_else(store, cfg)
    said = f"Correction: the fair invitations are {name}'s to send."
    step = {"op": "action.owners", "id": action_id, "owners": [name], "evidence": {"quote": said}}
    _, done = apply(
        store, cfg, [step], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=said
    )
    assert done == ["applied"]
    signals = [s.data for s in store.read().list("signal") if action_id in (s.data.get("refs") or [])]
    assert [(s["kind"], s["note"], s["changeset"]) for s in signals] == [("change_requested", said, cs)]
    learning = [r.data for r in store.read().list("request") if (r.data.get("about") or {}).get("kind") == "signal"]
    assert len(learning) == 1 and learning[0]["state"] == "queued" and not learning[0].get("cause")


def test_an_owner_given_to_a_to_do_that_had_none_corrects_nothing(env):
    ws, cfg, store = env
    action_id = waiting_for_an_owner(store, cfg)
    name = someone_else(store, cfg)
    said = f"The fair invitations are {name}'s to send."
    step = {"op": "action.owners", "id": action_id, "owners": [name], "evidence": {"quote": said}}
    apply(store, cfg, [step], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=said)
    assert not [s for s in store.read().list("signal") if action_id in (s.data.get("refs") or [])]


def _hold_answers(env, note: str, first: dict, second: dict) -> list:
    from tests.test_answers_and_voice import _returned_twice

    return _returned_twice(env, note, first, second)


def _note_only(text: str) -> dict:
    return {"summary": "Noted the hold.", "ops": [{"op": "note", "text": text}]}


def test_a_hold_in_the_persons_own_note_answered_only_with_a_note_goes_back_once_and_the_second_answer_stands(env):
    """The first-week journey (J-8): "Hold the gala invitations until Dana approves the guest list" was answered with a
    note and "nothing to put on hold". It goes back once asking whether the held thing is work to do; the decision
    stays with the model."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    try:
        asked = _hold_answers(env, NOTE, _note_only(NOTE), _note_only(NOTE))
        assert len(asked) == 2
        assert "holds something until a condition" in asked[1].request and "your answer stands" in asked[1].request
        assert any(n.data["text"] == NOTE for n in store.read().list("note"))
    finally:
        set_responder(None)


def test_a_hold_answered_with_a_to_do_on_hold_or_a_note_with_no_hold_is_not_sent_back(env):
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    try:
        todo = {"summary": "Held the invitations.", "ops": [HELD]}
        assert len(_hold_answers(env, NOTE, todo, todo)) == 1
        plain = "The fair needs more volunteers this year."
        assert len(_hold_answers(env, plain, _note_only(plain), _note_only(plain))) == 1
    finally:
        set_responder(None)
