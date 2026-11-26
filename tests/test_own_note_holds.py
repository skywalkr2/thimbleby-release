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


@pytest.fixture
def net_env(tmp_path):
    """The same workspace with the `guess-not-applied` net switched back on: it is off by default now that the app
    applies a waiting lesson itself (engine/guess_fit.py), and a workspace can turn it on again."""
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"checks.lints.guess-not-applied": "return"})
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


def _then_stronger(env) -> bool:
    """Whether a net on the person's own note, still missed after its one return round, went once to the stronger
    model (the #70 re-check: run 3's open choice kept as a fact stood on the cheapest model)."""
    _, _, store = env
    return [r.data["tier"] for r in store.read().list("run")][-2:] == ["deep", "deep"]


def _note_only(text: str) -> dict:
    return {"summary": "Noted the hold.", "ops": [{"op": "note", "text": text}]}


def test_a_hold_in_the_persons_own_note_answered_only_with_a_note_goes_back_once_then_to_the_stronger_model(env):
    """The first-week journey (J-8): "Hold the gala invitations until Dana approves the guest list" was answered with a
    note and "nothing to put on hold". It goes back once asking whether the held thing is work to do; the decision
    stays with the model."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    try:
        asked = _hold_answers(env, NOTE, _note_only(NOTE), _note_only(NOTE))
        assert len(asked) == 4 and _then_stronger(env)
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


def test_a_to_do_owed_to_someone_the_same_note_adds_comes_in_at_once_never_on_who_is_this(env):
    """The #67 re-check (N-7): "Marco Reyes… is waiting on our crate dimensions" added Marco and then held the
    person's own to-do on "Waiting for you to say who this is": the name lookup didn't know the person just added."""
    ws, cfg, store = env
    me = People(store, cfg).pm
    name = "Quillon " + "Varga"
    said = f"{name}, the conservator, is waiting on our crate dimensions."
    ops = [
        {"op": "person.add", "full_name": name, "role": "Conservator"},
        {
            "op": "action.add",
            "text": "Send the crate dimensions",
            "owners": [me],
            "promised_to": [name],
            "evidence": {"quote": said},
        },
    ]
    cs, done = apply(store, cfg, ops, origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=said)
    assert done == ["applied", "applied"]
    made = store.read().get("changeset", cs).data["ops"]
    added = made[0]["records"][0]["id"]
    action = store.read().get("action", made[1]["records"][0]["id"]).data
    assert action["promised_to"] == [added] and [o["person"] for o in action["owners"]] == [me]


@pytest.mark.parametrize("origin, trust, applied", [("pm", "trusted", True), ("input", "untrusted", False)])
def test_whether_the_person_runs_a_calendar_entry_comes_from_their_own_note_never_from_outside(
    env, origin, trust, applied
):
    """The #67 re-check (N-8): the person's own note's opening day as a calendar entry was refused with "only you say
    whether you run or attend a calendar entry"; their own note says so. Outside content still never does."""
    ws, cfg, store = env
    said = "I'm running the fair, which opens on March 14 at 10am."
    entry = {
        "op": "event.add",
        "title": "The fair opens",
        "start": "2027-03-14T10:00:00+00:00",
        "role": "run",
        "evidence": {"quote": "I'm running the fair, which opens on March 14 at 10am"},
    }
    cs, done = apply(store, cfg, [entry], origin=origin, trust=trust, source_id=source(store, trust=trust), raw=said)
    assert (done[0] != "refused") is applied, done


@pytest.mark.parametrize(
    "note",
    [
        "Put the fair invitations on hold until the board approves the guest list.",
        "Pause the fair mailing until the board approves the guest list.",
        "Don't send the fair invitations until the board approves the guest list.",
        "Don’t send the fair invitations until the board approves the guest list.",
        "Wait on the fair invitations until the board approves the guest list.",
    ],
)
def test_the_other_ways_to_hold_until_a_condition_answered_with_a_note_go_back_once(env, note):
    """The #67 re-check (B-12): "on hold until", "pause ... until" and "don't send ... until" hold like "hold"."""
    from engine.ai.adapters.stub import set_responder

    try:
        asked = _hold_answers(env, note, _note_only(note), _note_only(note))
        assert len(asked) == 4 and _then_stronger(env) and "holds something until a condition" in asked[1].request
    finally:
        set_responder(None)


def test_a_hold_of_a_meeting_that_does_something_with_it_is_never_sent_back(env):
    """The net is for notes and facts alone: "Hold the meeting until Friday" answered with the to-do on hold goes
    through, and a note with no hold in it is not sent back."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    note = "Hold the vendor meeting until Friday."
    held = {
        "op": "action.add",
        "text": "Hold the vendor meeting",
        "waiting_for": "Friday",
        "evidence": {"quote": "Hold the vendor meeting until Friday"},
    }
    try:
        assert len(_hold_answers(env, note, {"summary": "Held it.", "ops": [held]}, {"summary": "x", "ops": []})) == 1
    finally:
        set_responder(None)


UNDECIDED = "I haven't decided between matte and soft-touch for the cover yet."


def _decision(text: str) -> dict:
    return {
        "summary": "Asked you to choose between matte and soft-touch for the cover.",
        "ops": [
            {
                "op": "question.add",
                "to": "me",
                "kind": "decision",
                "title": "Cover finish: matte or soft-touch?",
                "text": text,
                "project": "PRJ-1",
                "would_change": {"what": "field", "record": "PRJ-1", "field": "summary"},
            }
        ],
    }


@pytest.mark.parametrize(
    "note",
    [
        UNDECIDED,
        "We still have to pick the cover paper, A or B.",
        "Still undecided on the date.",
        "I'm torn between matte and soft-touch for the cover.",
        "I'm not sure yet which paper to use for the cover.",
        "Cover finish: tbd.",
    ],
)
def test_a_choice_still_open_answered_with_only_a_note_goes_back_once_then_to_the_stronger_model(env, note):
    """The #67 re-check (B-6): "I haven't decided" became a note. It goes back once asking whether it is a decision
    for the person; the decision stays with the model."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    try:
        asked = _hold_answers(env, note, _note_only(note), _note_only(note))
        assert len(asked) == 4 and _then_stronger(env)
        assert "choice is still open" in asked[1].request and "your answer stands either way" in asked[1].request
        assert any(n.data["text"] == note for n in store.read().list("note"))
    finally:
        set_responder(None)


def test_a_decision_question_for_an_open_choice_or_a_note_with_no_open_choice_is_not_sent_back(env):
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    try:
        assert len(_hold_answers(env, UNDECIDED, _decision("Matte or soft-touch."), _decision("x"))) == 1
        plain = "The fair needs more volunteers this year."
        assert len(_hold_answers(env, plain, _note_only(plain), _note_only(plain))) == 1
    finally:
        set_responder(None)


@pytest.mark.parametrize(
    "note",
    ["I haven't decided to quit the committee.", "I haven’t decided to move the launch.", "The tbdx list is long."],
)
def test_a_decision_already_made_or_a_lookalike_word_is_no_open_choice(env, note):
    """The #68 re-check (B-14): "haven't decided to quit" names no choice; "TBD" is a whole word only."""
    from engine.ai.adapters.stub import set_responder

    try:
        assert len(_hold_answers(env, note, _note_only(note), _note_only(note))) == 1
    finally:
        set_responder(None)


def test_a_decision_question_for_a_torn_choice_or_a_wait_with_a_to_do_is_not_sent_back(env):
    from engine.ai.adapters.stub import set_responder

    try:
        note = "I'm torn between matte and soft-touch for the cover."
        assert len(_hold_answers(env, note, _decision("Matte or soft-touch."), _decision("x"))) == 1
    finally:
        set_responder(None)


def test_a_project_whose_day_the_note_gives_with_no_year_comes_in_with_the_next_such_day(env):
    """The #68 re-check (N-7): the instructions say a day with no year is written "--MM-DD" and the app gives the year,
    but a project's day took only a full date, so Haiku's right answer was refused as unreadable five times before one
    left the day out. A project's day takes the next such day on or after the note, like a to-do's."""
    from datetime import date

    ws, cfg, store = env
    note = "I'm running the Volunteer Gala on February 6."
    add = {
        "op": "project.add",
        "name": "Volunteer Gala",
        "target": "--02-06",
        "evidence": {"quote": "the Volunteer Gala on February 6"},
    }
    cs, done = apply(
        store, cfg, [add], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=note
    )
    assert done == ["applied"]
    record = store.read().get("changeset", cs).data["ops"][0]["records"][0]
    target = date.fromisoformat(store.read().get("project", record["id"]).data["target"])
    received = date.fromisoformat(store.clock()[:10])
    assert (target.month, target.day) == (2, 6) and received <= target < received.replace(year=received.year + 1)


def test_a_question_asking_who_owns_a_to_do_the_same_answer_gave_an_owner_goes_back_once(env):
    """The #68 re-check (N-11): Sonnet made the crate to-do the person's own and asked "Who should send Marco the crate
    dimensions, and by what date?" in the same answer. It goes back once; the answer stands either way."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    me = People(store, cfg).pm
    note = "The shop is waiting on our crate dimensions."
    todo = {
        "op": "action.add",
        "text": "Send the shop the crate dimensions",
        "owners": [me],
        "evidence": {"quote": note},
    }
    asks = {
        "op": "question.add",
        "title": "Who sends the shop the crate dimensions?",
        "text": "Who should send the shop the crate dimensions?",
        "to": me,
        "would_change": {"what": "owner", "record": "$new:0"},
    }
    both = {"summary": "Added the crate to-do.", "ops": [todo, asks]}
    try:
        asked = _hold_answers(env, note, both, both)
        assert len(asked) == 2 and "already gives to" in asked[1].request and "answer stands" in asked[1].request
        alone = {"summary": "Added the crate to-do.", "ops": [todo]}
        assert len(_hold_answers(env, note, alone, alone)) == 1
    finally:
        set_responder(None)


def test_a_question_asking_who_owns_a_to_do_the_answer_left_without_an_owner_is_not_sent_back(env):
    """The #70 re-check (B-7): the applier fills the person in on a to-do the answer gave no owner, and the lint read
    that filled-in owner as one the answer had given. Only the owners the answer itself gave count."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    me = People(store, cfg).pm
    note = "The shop is waiting on our crate dimensions."
    todo = {"op": "action.add", "text": "Send the shop the crate dimensions", "evidence": {"quote": note}}
    asks = {
        "op": "question.add",
        "title": "Who sends the shop the crate dimensions?",
        "text": "Who should send the shop the crate dimensions?",
        "to": me,
        "would_change": {"what": "owner", "record": "$new:0"},
    }
    both = {"summary": "Added the crate to-do.", "ops": [todo, asks]}
    try:
        got = _hold_answers(env, note, both, both)
        assert len(got) == 1, got[-1].request[-600:]
    finally:
        set_responder(None)


def test_a_choice_still_open_kept_only_as_a_fact_goes_back_once(env):
    """The #70 re-check (B-3): "I haven't decided" came back as the fact "no choice has been made", so there was no
    question to close later. Facts are read like notes."""
    from engine.ai.adapters.stub import set_responder

    fact = {
        "summary": "Noted that no caterer is chosen.",
        "ops": [
            {
                "op": "fact",
                "text": "No choice has been made between matte and soft-touch for the cover.",
                "evidence": {"quote": "I haven't decided between matte and soft-touch"},
            }
        ],
    }
    try:
        asked = _hold_answers(env, UNDECIDED, fact, fact)
        assert len(asked) == 4 and _then_stronger(env) and "choice is still open" in asked[1].request
    finally:
        set_responder(None)


@pytest.mark.parametrize(
    "note",
    [
        "The gala invitations are on ice until Dana approves the guest list.",
        "Wait for Dana to approve the guest list before the gala invitations go out.",
    ],
)
def test_a_hold_said_as_on_ice_or_wait_for_before_answered_with_a_note_goes_back_once(env, note):
    """The #70 re-check (B-9): "on ice until" and "wait for … before" hold something like "hold … until" does."""
    from engine.ai.adapters.stub import set_responder

    try:
        asked = _hold_answers(env, note, _note_only(note), _note_only(note))
        assert len(asked) == 4 and _then_stronger(env) and "holds something until a condition" in asked[1].request
    finally:
        set_responder(None)


@pytest.mark.parametrize(
    "note",
    ["I haven't made a decision on the caterer.", "No decision yet on the venue.", "I'm still deciding on the paper."],
)
def test_more_ways_of_saying_a_choice_is_open_kept_as_a_note_go_back_once(env, note):
    from engine.ai.adapters.stub import set_responder

    try:
        asked = _hold_answers(env, note, _note_only(note), _note_only(note))
        assert len(asked) == 4 and _then_stronger(env) and "choice is still open" in asked[1].request
    finally:
        set_responder(None)


def test_a_year_less_day_works_in_record_set_and_in_days_away(env):
    """The #70 re-check (N-4): the instructions ask for --MM-DD for every day with no year, but `record.set` on a
    project's target refused --03-14 and `person.away` with --12-20 made the whole answer unreadable. Both take the
    next such day; days away are a range, so an end in January after a start in December is the next year's."""
    from datetime import date

    ws, cfg, store = env
    received = date.fromisoformat(store.clock()[:10])
    project = next(p for p in store.read().list("project") if p.data.get("status", "active") != "done")
    note = f"{project.data['name']} now opens March 14."
    moved = {
        "op": "record.set",
        "kind": "project",
        "id": project.id,
        "field": "target",
        "value": "--03-14",
        "evidence": {"quote": f"{project.data['name']} now opens March 14"},
    }
    cs, done = apply(
        store, cfg, [moved], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=note
    )
    assert done == ["applied"]
    target = date.fromisoformat(store.read().get("project", project.id).data["target"])
    assert (target.month, target.day) == (3, 14) and received <= target < received.replace(year=received.year + 1)

    me = People(store, cfg).pm
    away_note = "I'm off Dec 20 to Jan 5."
    away = {"op": "person.away", "person": me, "start": "--12-20", "end": "--01-05", "evidence": {"quote": away_note}}
    cs, done = apply(
        store, cfg, [away], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=away_note
    )
    assert done == ["applied"]
    record = store.read().get("changeset", cs).data["ops"][0]["op"]
    first, last = date.fromisoformat(record["start"]), date.fromisoformat(record["end"])
    assert (first.month, first.day, last.month, last.day) == (12, 20, 1, 5) and last.year == first.year + 1


def test_a_29_february_with_no_year_far_off_goes_back_for_its_year_and_a_full_date_does_not(env):
    """The #70 re-check (N-4): --02-29 silently became 2028-02-29, fifteen months out. When the nearest one is more than
    a year away it goes back once to be given its year."""
    from datetime import date

    from engine.applier import Context, Inputs, check
    from engine.ops import CHANGESET

    ws, cfg, store = env
    note = "The Volunteer Gala is on February 29."

    def found(target: str) -> list:
        add = {"op": "project.add", "name": "Volunteer Gala", "target": target, "evidence": {"quote": note.rstrip(".")}}
        cs = CHANGESET.validate_python({"ops": [add]}, context={"op_models": store.plugins.ops})
        ctx = Context(
            store, cfg, People(store, cfg), tuple(store.plugins.ops), Inputs("REQ-1", "SRC-1", note, "", "trusted")
        )
        return [p for p in check(cs, ctx) if p.check == "leap-day-without-year"]

    received = date_of(store)
    leap_ahead = next(y for y in range(received.year, received.year + 5) if y % 4 == 0)
    far = (date(leap_ahead, 2, 29) - received).days > 366
    assert bool(found("--02-29")) == far
    assert found(f"{leap_ahead}-02-29") == []


def date_of(store):
    from datetime import date

    return date.fromisoformat(store.clock()[:10])


def _waiting_routing(store, cfg, project_name: str) -> tuple[str, str]:
    """A routing entry the person's correction taught for a project's kind of work, waiting for their Keep."""
    from engine.storage import WriteContext

    me = People(store, cfg).pm
    other = next(p.id for p in store.read().list("person") if p.id != me and p.data.get("full_name"))
    with store.transaction() as tx:
        entry = tx.create(
            "routing_entry",
            {
                "topic": f"what goes out for {project_name}",
                "text": f"What goes out for {project_name} is this person's to send.",
                "person": other,
                "kind_of_work": f"what goes out for {project_name}",
                "origin": "assistant",
                "status": "proposed",
                "guess_until_kept": True,
                "learned_at": "2026-11-19T09:00:00+00:00",
                "applies_to": {},
            },
            WriteContext("engine", "trusted", "test"),
        )
    return entry.id, other


def test_a_to_do_of_a_waiting_guess_kind_given_to_the_user_goes_back_once_then_to_the_stronger_model(net_env):
    """The #70 re-check (N-2): the not-yet-kept lesson was used in two runs of three, and row 11 measured ten times on
    Haiku used it seven times even at the top of the packet. A to-do about the same project as the guess's kind of
    work, given to the user while the note names nobody, goes back once and then once to the stronger model; whether it
    is that kind of work stays the assistant's."""
    from engine.ai.adapters.stub import set_responder

    env = net_env
    ws, cfg, store = env
    project = next(p for p in store.read().list("project"))
    entry, other = _waiting_routing(store, cfg, project.data["name"])
    note = f"We also need to send the {project.data['name']} sponsor letters."
    mine = {
        "summary": "Added the letters.",
        "ops": [
            {
                "op": "action.add",
                "text": f"Send the {project.data['name']} sponsor letters",
                "evidence": {"quote": note},
            }
        ],
    }
    theirs = {
        "summary": "Added the letters.",
        "ops": [{**mine["ops"][0], "owners": [other]}],
        "by_kind": [{"op": 0, "entry": entry}],
    }
    try:
        asked = _hold_answers(env, note, mine, mine)
        assert len(asked) == 4 and _then_stronger(env) and entry in asked[1].request
        assert "answer stands either way" in asked[1].request
        assert len(_hold_answers(env, note, theirs, theirs)) == 1
        partner = store.read().get("person", other).data["full_name"]
        named = f"I'll send the {project.data['name']} sponsor letters myself, with {partner}."
        own = {"summary": "Added the letters.", "ops": [{**mine["ops"][0], "evidence": {"quote": named}}]}
        got = _hold_answers(env, named, own, own)
        # The note names someone: whose work it is was the assistant's call, so this net never points at it.
        assert all("not yet kept, says" not in task.request for task in got)
    finally:
        set_responder(None)


def test_a_year_less_reminder_repeat_start_and_as_of_day_are_read_and_a_backwards_span_away_goes_back(env):
    """The #71 re-check (N-3): `remind_at` written --12-20T09:00, an `action.repeat` start or a fact's `as_of`
    written --MM-DD made the whole answer unreadable, and days away "Dec 20 to Dec 5" became a year-long span with no
    question."""
    from datetime import date, datetime

    from engine.applier import Context, Inputs, apply_as_person, check
    from engine.ops import CHANGESET

    ws, cfg, store = env
    received = date.fromisoformat(store.clock()[:10])
    me = People(store, cfg).pm
    from engine.storage import WriteContext

    with store.transaction() as tx:
        action = tx.create(
            "action",
            {"text": "Water the plants", "owners": [{"person": me}], "status": "open"},
            WriteContext("pm", "trusted", "test"),
        )
    remind = {"op": "record.set", "kind": "action", "id": action.id, "field": "remind_at", "value": "--12-20T09:00"}
    apply_as_person(store, cfg, [remind], "Remind me Dec 20")
    when = datetime.fromisoformat(store.read().get("action", action.id).data["remind_at"])
    assert (when.month, when.day, when.hour) == (12, 20, 9) and when.tzinfo is not None and when.date() >= received

    repeat = {"op": "action.repeat", "id": action.id, "rule": "FREQ=WEEKLY", "phrase": "every week", "start": "--12-01"}
    apply_as_person(store, cfg, [repeat], "Repeat it")
    start = date.fromisoformat(store.read().get("action", action.id).data["repeat"]["start"])
    assert (start.month, start.day) == (12, 1) and start >= received

    note = "As of Nov 3 the hall holds 120."
    fact = {"op": "fact", "text": "The hall holds 120", "as_of": "--11-03", "evidence": {"quote": note}}
    cs, done = apply(
        store, cfg, [fact], origin="pm", trust="trusted", source_id=source(store, trust="trusted"), raw=note
    )
    assert done == ["applied"]
    kept = store.read().get("changeset", cs).data["ops"][0]["op"]
    as_of = date.fromisoformat(kept["as_of"])
    assert (as_of.month, as_of.day) == (11, 3) and as_of <= received

    def spans(start: str, end: str) -> list:
        quote = "I'm away for a while."
        away = {"op": "person.away", "person": me, "start": start, "end": end, "evidence": {"quote": quote}}
        cs = CHANGESET.validate_python({"ops": [away]}, context={"op_models": store.plugins.ops})
        ctx = Context(
            store, cfg, People(store, cfg), tuple(store.plugins.ops), Inputs("REQ-1", "SRC-1", quote, "", "trusted")
        )
        return [p for p in check(cs, ctx) if p.check == "away-span-long"]

    assert spans("--12-20", "--12-05") and not spans("--12-20", "--01-05") and not spans("--06-01", "--07-15")


def test_an_answer_to_the_persons_own_note_that_keeps_nothing_goes_back_and_the_note_is_never_dropped(env):
    """The #71 re-check (N-1): "Book the photographer for the gala." came back as "no operation here can book a
    photographer, so nothing was recorded". An answer to the person's own note that keeps nothing goes back once, then
    once to the stronger model; if it still keeps nothing, the note itself is kept."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    project = next(p for p in store.read().list("project"))
    note = f"Book the photographer for {project.data['name']}."
    empty = {"summary": "No operation here can book a photographer, so nothing was recorded.", "ops": []}
    mine = {
        "summary": "Added the to-do.",
        "ops": [{"op": "action.add", "text": "Book the photographer", "evidence": {"quote": note.rstrip(".")}}],
    }
    try:
        before = len(store.read().list("note"))
        asked = _hold_answers(env, note, empty, empty)
        assert len(asked) == 4 and _then_stronger(env) and "records nothing" in asked[1].request
        assert [n.data["text"] for n in store.read().list("note")][before:] == [note]
        assert len(_hold_answers(env, note, mine, mine)) == 1
    finally:
        set_responder(None)


@pytest.mark.parametrize("shape", ["marked-but-mine", "unmarked-and-mine-by-name"])
def test_an_answer_that_names_the_waiting_guess_but_keeps_the_to_do_the_users_still_goes_back(net_env, shape):
    """The #72 re-check (N-1): the net fired in one run of three. Naming the entry in "by_kind" while the to-do stayed
    the user's counted as applying it, so the net let it pass and the to-do was even marked as the guess while still
    the user's. Only the entry's person owning the to-do applies it; a mark on a to-do they don't own is not kept."""
    from engine.ai.adapters.stub import set_responder

    env = net_env
    ws, cfg, store = env
    project = next(p for p in store.read().list("project"))
    entry, other = _waiting_routing(store, cfg, project.data["name"])
    me = People(store, cfg).pm
    note = f"We also need to send the {project.data['name']} sponsor letters."
    add = {"op": "action.add", "text": f"Send the {project.data['name']} sponsor letters", "evidence": {"quote": note}}
    if shape == "marked-but-mine":
        answer = {"summary": "Added the letters.", "ops": [add], "by_kind": [{"op": 0, "entry": entry}]}
    else:
        name = store.read().get("person", me).data["full_name"]
        answer = {"summary": "Added the letters.", "ops": [{**add, "owners": [name]}]}
    try:
        asked = _hold_answers(env, note, answer, answer)
        assert len(asked) == 4 and _then_stronger(env) and entry in asked[1].request
        letters = [a for a in store.read().list("action") if "sponsor letters" in a.data["text"]]
        assert letters and all(not (a.data.get("by_kind") or {}).get("entry") for a in letters)
    finally:
        set_responder(None)


def test_a_promise_in_the_persons_own_note_left_out_of_an_otherwise_good_answer_goes_back_then_to_the_stronger_model(
    env,
):
    """The #72 re-check (N-2): the meeting note's answer kept the person's two to-dos and nothing of "She'll confirm
    the quote next week", and the nets passed it: the promise net reads facts and the empty-answer net needs nothing
    kept. A sentence where someone else promises something, which no op quotes and no op names them in, sends the
    answer back once and then once to the stronger model; an answer that keeps it, or a note where only the user
    promises, doesn't."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    me = People(store, cfg).pm
    other = next(p for p in store.read().list("person") if p.id != me and p.data.get("full_name"))
    first = other.data["full_name"]  # in full: a first name two people share names nobody
    budget, promise = "I need to send her the draft budget by Friday.", "She'll confirm the printer's quote next week."
    note = f"Met with {first} this morning. {budget} {promise}"
    mine = {"op": "action.add", "text": "Send the draft budget", "owners": [me], "evidence": {"quote": budget}}
    dropped = {"summary": "Added the budget to-do.", "ops": [mine]}
    kept = {
        "summary": "Added both.",
        "ops": [
            mine,
            {
                "op": "action.add",
                "text": "Confirm the printer's quote",
                "owners": [other.id],
                "evidence": {"quote": promise},
            },
        ],
    }
    try:
        asked = _hold_answers(env, note, dropped, dropped)
        assert len(asked) == 4 and _then_stronger(env) and "nothing in this answer keeps" in asked[1].request
        assert len(_hold_answers(env, note, kept, kept)) == 1
        mine_only = f"Met with {first} this morning. I'll send the draft budget by Friday."
        own = {"summary": "Added it.", "ops": [{**mine, "evidence": {"quote": "I'll send the draft budget by Friday"}}]}
        assert all("nothing in this answer keeps" not in t.request for t in _hold_answers(env, mine_only, own, own))
    finally:
        set_responder(None)


def test_a_state_after_a_promise_word_or_a_promise_kept_by_who_said_it_is_never_sent_back_as_left_out(env):
    """The #73 re-check (N-3): `promise-left-out` cost row 2 four calls in two runs, and it fired on "<name> will be
    out Friday" and "will be at the fair on Saturday". A promise word before be, been, have or had is a state, as the
    promise-as-fact net reads it, and a promise the answer keeps with its promiser as `said_by` is kept."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    me = People(store, cfg).pm
    other = next(p for p in store.read().list("person") if p.id != me and p.data.get("full_name"))
    first = other.data["full_name"]
    budget = "I need to send the draft budget by Friday."
    mine = {"op": "action.add", "text": "Send the draft budget", "owners": [me], "evidence": {"quote": budget}}
    answer = {"summary": "Added the budget to-do.", "ops": [mine]}
    try:
        for state in (f"{first} will be out Friday.", f"{first} will be at the fair on Saturday."):
            asked = _hold_answers(env, f"{budget} {state}", answer, answer)
            assert all("nothing in this answer keeps" not in t.request for t in asked), state
        promise = f"{first} will confirm the printer's quote next week."
        said = {
            "op": "action.add",
            "text": "Get the printer's quote confirmed",
            "owners": [me],
            "said_by": other.id,
            "evidence": {"quote": "confirm the printer's quote"},
        }
        kept = {"summary": "Added both.", "ops": [mine, said]}
        asked = _hold_answers(env, f"{budget} {promise}", kept, kept)
        assert all("nothing in this answer keeps" not in t.request for t in asked)
    finally:
        set_responder(None)


def test_one_date_question_for_the_to_dos_an_answer_adds_with_no_date_is_not_sent_back_as_changing_nothing(env):
    """The #73 re-check (N-3): row 2's slow runs went back for a question that changes nothing. `undated-todo` asks
    for one date question for all the to-dos with no date, and that question can name only one of them in
    `would_change`; it settles their days, so it is not sent back. A question about nothing in the answer still is."""
    from engine.ai.adapters.stub import set_responder

    ws, cfg, store = env
    me = People(store, cfg).pm
    note = "I need to send the crate sizes and book the movers."
    todos = [
        {"op": "action.add", "text": text, "owners": [me], "evidence": {"quote": note}}
        for text in ("Send the crate sizes", "Book the movers")
    ]
    ask = {
        "op": "question.add",
        "kind": "question",
        "to": me,
        "asks_about": "date",
        "title": "What dates for the crate sizes and the movers?",
        "text": "Two to-dos from your note have no day yet, the crate sizes and the movers. What day is each due?",
    }
    try:
        asked = _hold_answers(env, note, {"summary": "Added both.", "ops": [*todos, ask]}, {"ops": [*todos, ask]})
        assert all("names nothing its answer would change" not in t.request for t in asked)
        dated = [{**t, "due": "2026-12-04"} for t in todos]
        asked = _hold_answers(env, note, {"summary": "Added both.", "ops": [*dated, ask]}, {"ops": [*dated, ask]})
        assert any("names nothing its answer would change" in t.request for t in asked)
    finally:
        set_responder(None)


def test_when_the_guess_net_stands_down_on_a_to_do_given_to_the_user_the_log_says_why_by_ids_only(net_env, caplog):
    """The #73 re-check (N-2): run 2's answer gave the gala letters to the user in one call with the lesson given, and
    nothing in the install showed why the net let it pass. When a guess waits and a to-do goes to the user, the net
    logs why it stood down, by ids only, so the log a person sends with a report traces it."""
    import logging

    from engine.ai.adapters.stub import set_responder

    env = net_env
    ws, cfg, store = env
    project = next(p for p in store.read().list("project"))
    entry, other = _waiting_routing(store, cfg, project.data["name"])
    me = People(store, cfg).pm
    full = store.read().get("person", other).data["full_name"]
    note = f"We also need to send the {project.data['name']} sponsor letters, {full} says."
    add = {"op": "action.add", "text": "Send the sponsor letters", "owners": [me], "evidence": {"quote": note}}
    answer = {"summary": "Added the letters.", "ops": [add]}
    try:
        with caplog.at_level(logging.WARNING, logger="engine.applier"):
            _hold_answers(env, note, answer, answer)
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("guess net:")]
        assert lines and other in lines[0] and "sponsor" not in " ".join(lines)
    finally:
        set_responder(None)
