"""What was learned for one item applies to an item only of its kind of work as a guess the person sees, marked on
its row with one click to take it back. The run
names such a step in "by_kind"; the to-do it makes keeps the entry, its kind of work, the day it was learned and the
owners it would have had."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.applier import Context, Inputs, apply_changeset
from engine.knowledge_section import _entry_line
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_knowledge_records import request, source

NOTE = "We also need to send the fair sponsor thank-you letters."
KIND = "what goes out for the fair"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()


def run(store, cfg, answer: dict, *, origin="pm", trust="trusted", ai_run: str | None = None, note: str = NOTE) -> str:
    cs = CHANGESET.validate_python(answer, context={"op_models": store.plugins.ops})
    src = source(store, trust=trust)
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request(store, origin, source=src), src, note, "", trust),
    )
    return apply_changeset(cs, [], ctx, run=ai_run)


def someone(store, cfg) -> tuple[str, str]:
    me = People(store, cfg).pm
    found = next(p for p in store.read().list("person") if p.id != me)
    return found.id, found.data["full_name"]


def learned(store, cfg, *, kind: str | None = KIND) -> str:
    pid, name = someone(store, cfg)
    entry = {"op": "lesson.add", "text": f"The fair invitations are {name}'s to send."}
    if kind:
        entry["kind_of_work"] = kind
    cs = run(store, cfg, {"ops": [entry]})
    return store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]


def letters(store, cfg, entry: str | None) -> dict:
    pid, name = someone(store, cfg)
    add = {
        "op": "action.add",
        "text": "Send the fair sponsor thank-you letters",
        "owners": [name],
        "evidence": {"quote": NOTE},
    }
    answer = {"ops": [add], **({"by_kind": [{"op": 0, "entry": entry}]} if entry else {})}
    cs = run(store, cfg, answer)
    made = store.read().get("changeset", cs).data["ops"][0]
    return made, store.read().get("action", made["records"][0]["id"]).data


def test_a_step_decided_by_a_kind_of_work_is_marked_on_the_to_do_with_the_day_and_the_owners_it_would_have_had(env):
    ws, cfg, store = env
    entry = learned(store, cfg)
    outcome, action = letters(store, cfg, entry)
    mark = action["by_kind"]
    assert mark["entry"] == entry and mark["kind_of_work"] == KIND and mark["learned_on"]
    assert mark["owners_before"] == [People(store, cfg).pm]
    assert outcome["by_kind"]["entry"] == entry


def test_a_step_that_names_no_kind_or_an_entry_without_one_is_not_marked(env):
    ws, cfg, store = env
    assert letters(store, cfg, None)[1].get("by_kind") is None
    narrow = learned(store, cfg, kind=None)
    assert letters(store, cfg, narrow)[1].get("by_kind") is None
    assert letters(store, cfg, "LES-999")[1].get("by_kind") is None


def test_the_packet_line_keeps_the_item_and_offers_the_kind_as_a_guess(env):
    ws, cfg, store = env
    entry = store.read().get("lesson", learned(store, cfg))
    line = _entry_line(entry)
    assert entry.data["text"] in line and KIND in line and '"by_kind"' in line
    narrow = store.read().get("lesson", learned(store, cfg, kind=None))
    assert "by_kind" not in _entry_line(narrow)


def test_an_answers_by_kind_survives_reading_and_is_shown_back_in_a_return_round():
    """The answer is read by the dispatcher's parse, which keeps only the keys that mean something at the top: a
    by_kind it dropped never reached the applier, and a return round showed the model an empty one to copy."""
    import json

    from engine.dispatcher import _answer_shown, parse
    from engine.ops import schema_for

    text = json.dumps(
        {
            "summary": "x",
            "ops": [{"op": "note", "text": "The letters go out next week."}],
            "by_kind": [{"op": 0, "entry": "LES-1"}, {"op": "first", "entry": 7}],
        }
    )
    cs = parse(text)
    assert [(g.op, g.entry) for g in cs.by_kind] == [(0, "LES-1")]
    assert '"by_kind": [{"op": 0, "entry": "LES-1"}]' in _answer_shown(cs)
    assert "by_kind" in schema_for(["note"])["properties"]


def test_taking_back_a_guess_puts_back_the_owners_clears_the_mark_and_teaches_that_the_kind_was_too_wide(env):
    from engine.applier import apply_as_person

    ws, cfg, store = env
    entry = learned(store, cfg)
    outcome, action = letters(store, cfg, entry)
    action_id = outcome["records"][0]["id"]
    before = action["by_kind"]["owners_before"]
    apply_as_person(store, cfg, [{"op": "action.owners", "id": action_id, "owners": before}], "Took back a guess")
    after = store.read().get("action", action_id).data
    assert [o["person"] for o in after["owners"]] == before and after.get("by_kind") is None
    signals = [s.data for s in store.read().list("signal") if action_id in (s.data.get("refs") or [])]
    assert len(signals) == 1 and signals[0]["kind"] == "change_requested"
    assert entry in signals[0]["note"] and KIND in signals[0]["note"]


@pytest.fixture
def api(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    app = create_app(ws, cfg, "by-kind-token", ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": "Bearer by-kind-token"}) as client:
        yield client, cfg, app.state.store


def test_the_row_of_a_guess_says_what_it_came_from_and_one_click_takes_it_back(api):
    client, cfg, store = api
    entry = learned(store, cfg)
    outcome, action = letters(store, cfg, entry)
    action_id = outcome["records"][0]["id"]
    row = next(a for a in client.get("/api/open-items").json()["actions"] if a["id"] == action_id)
    assert row["guess"] == {
        "kind_of_work": KIND,
        "learned_on": action["by_kind"]["learned_on"],
        "can_take_back": True,
    }
    done = client.post(f"/api/actions/{action_id}/take-back-guess")
    assert done.status_code == 200 and done.json()["changeset"]
    row = next(a for a in client.get("/api/open-items").json()["actions"] if a["id"] == action_id)
    assert row["guess"] is None
    assert [o["person"] for o in row["owners"]] == action["by_kind"]["owners_before"]
    # Nothing is left to take back, and a to-do that never had a guess says so rather than changing.
    assert client.post(f"/api/actions/{action_id}/take-back-guess").status_code == 409


def test_a_to_do_with_no_guess_has_no_mark_on_its_row(api):
    client, cfg, store = api
    outcome, _ = letters(store, cfg, None)
    row = next(a for a in client.get("/api/open-items").json()["actions"] if a["id"] == outcome["records"][0]["id"])
    assert row["guess"] is None


def test_the_persons_own_change_of_owners_ends_the_guess_so_take_it_back_never_undoes_it(env):
    """The #67 re-check (N-4): reassigning a guessed to-do from its row left the mark, and Take it back then put the
    guessed owner back over the person's choice."""
    from engine.applier import apply_as_person

    ws, cfg, store = env
    entry = learned(store, cfg)
    outcome, action = letters(store, cfg, entry)
    action_id = outcome["records"][0]["id"]
    me = People(store, cfg).pm
    chosen = next(p.id for p in store.read().list("person") if p.id not in (me, action["owners"][0]["person"]))
    current = store.read().get("action", action_id)
    edit = {
        "op": "record.edit",
        "record": {"kind": "action", "id": action_id},
        "fields": {"owners": [{"person": chosen}]},
        "read_version": current.version,
    }
    apply_as_person(store, cfg, [edit], "Changed on screen")
    after = store.read().get("action", action_id).data
    assert [o["person"] for o in after["owners"]] == [chosen] and after.get("by_kind") is None


def waiting_guess(store, cfg, *, flagged: bool = True) -> str:
    """A lesson the person's correction taught that waits for their Keep (it grants power)."""
    from engine.storage import WriteContext

    pid, name = someone(store, cfg)
    with store.transaction() as tx:
        return tx.create(
            "lesson",
            {
                "text": f"The fair invitations are {name}'s to send.",
                "kind_of_work": KIND,
                "origin": "assistant",
                "status": "proposed",
                "guess_until_kept": flagged,
                "learned_at": "2026-10-09T09:00:00+00:00",
                "applies_to": {},
            },
            WriteContext("engine", "trusted", "test"),
        ).id


def test_what_a_correction_taught_and_waits_for_keep_is_given_as_a_guess_and_marks_what_it_decides(env):
    """The #67 re-check (N-3): row 10's lesson stayed proposed, so row 11's letters came to the person. Until it is
    kept, a run is given it only as a guess, and the to-do it decides is marked with Take it back."""
    from engine.knowledge_section import _guess_line

    ws, cfg, store = env
    entry = waiting_guess(store, cfg)
    line = _guess_line(store.read().get("lesson", entry))
    assert "Not yet kept" in line and '"by_kind"' in line and KIND in line
    outcome, action = letters(store, cfg, entry)
    assert action["by_kind"]["entry"] == entry and action["by_kind"]["owners_before"] == [People(store, cfg).pm]


def test_a_proposal_that_is_not_from_the_persons_correction_is_never_given_or_marked(env):
    ws, cfg, store = env
    entry = waiting_guess(store, cfg, flagged=False)
    outcome, action = letters(store, cfg, entry)
    assert action.get("by_kind") is None


def given_run(store, cfg, entry: str) -> str:
    """An AI run whose knowledge log lists the entry as given."""
    from engine.storage import WriteContext

    task = next(iter(cfg.ai.tasks))
    data = {
        "task": task,
        "provider": "stub",
        "model": "example-small-model",
        "tier": "routine",
        "outcome": "ok",
        "started_at": "2026-10-10T09:00:00+00:00",
        "knowledge": {"given": [entry]},
    }
    with store.transaction() as tx:
        return tx.create("run", data, WriteContext("engine", "trusted", "test")).id


def test_a_to_do_owned_by_whom_a_not_yet_kept_lesson_names_is_marked_even_when_the_run_says_nothing(env):
    """The #68 re-check (N-4): the mark came only when the model listed the step in "by_kind", so a run that applied
    the lesson without saying so gave the owner with no mark and no Take it back. A run given the lesson whose to-do
    goes to someone only the lesson names is marked all the same."""
    ws, cfg, store = env
    entry = waiting_guess(store, cfg)
    pid, name = someone(store, cfg)
    add = {
        "op": "action.add",
        "text": "Send the fair sponsor thank-you letters",
        "owners": [name],
        "evidence": {"quote": NOTE},
    }
    cs = run(store, cfg, {"ops": [add]}, ai_run=given_run(store, cfg, entry))
    made = store.read().get("changeset", cs).data["ops"][0]
    action = store.read().get("action", made["records"][0]["id"]).data
    assert action["by_kind"]["entry"] == entry and action["by_kind"]["owners_before"] == [People(store, cfg).pm]


def test_a_to_do_whose_owner_the_input_names_or_a_run_not_given_the_lesson_is_never_marked(env):
    ws, cfg, store = env
    entry = waiting_guess(store, cfg)
    pid, name = someone(store, cfg)
    add = {
        "op": "action.add",
        "text": "Send the fair sponsor thank-you letters",
        "owners": [name],
        "evidence": {"quote": NOTE},
    }
    other = waiting_guess(store, cfg, flagged=False)
    not_given = run(store, cfg, {"ops": [add]}, ai_run=given_run(store, cfg, other))
    action = store.read().get("action", store.read().get("changeset", not_given).data["ops"][0]["records"][0]["id"])
    assert action.data.get("by_kind") is None
    named_note = f"{name} will send the fair sponsor thank-you letters."
    add_named = {**add, "evidence": {"quote": named_note}}
    named = run(store, cfg, {"ops": [add_named]}, ai_run=given_run(store, cfg, entry), note=named_note)
    action = store.read().get("action", store.read().get("changeset", named).data["ops"][0]["records"][0]["id"])
    assert action.data.get("by_kind") is None


def test_discarding_a_not_yet_kept_lesson_offers_its_guesses_and_one_step_takes_them_all_back_teaching_nothing(api):
    """The #68 re-check (N-5): discarding the lesson left its earlier guesses in place, each needing its own Take it
    back. Its guesses are counted for the discard, and one step takes them all back as one change with one Undo, with
    no correction of its own: the discard already taught."""
    client, cfg, store = api
    entry = waiting_guess(store, cfg)
    first, _ = letters(store, cfg, entry)
    second, _ = letters(store, cfg, entry)
    marked = [first["records"][0]["id"], second["records"][0]["id"]]
    lesson = store.read().get("lesson", entry)
    assert client.post(f"/api/knowledge/{entry}/discard", json={"read_version": lesson.version}).status_code == 200
    assert client.get(f"/api/knowledge/{entry}/guesses").json() == {"entry": entry, "count": 2}
    signals = len(store.read().list("signal"))
    proposed = len([x for x in store.read().list("lesson") if x.data.get("status") == "proposed"])
    done = client.post(f"/api/knowledge/{entry}/take-back-guesses")
    assert done.status_code == 200
    me = People(store, cfg).pm
    for action_id in marked:
        after = store.read().get("action", action_id).data
        assert after.get("by_kind") is None and [o["person"] for o in after["owners"]] == [me]
    assert store.read().get("changeset", done.json()["changeset"]).data["ops"][1]["status"] == "applied"
    assert len(store.read().list("signal")) == signals
    assert len([x for x in store.read().list("lesson") if x.data.get("status") == "proposed"]) == proposed
    assert client.get(f"/api/knowledge/{entry}/guesses").json()["count"] == 0
    assert client.post(f"/api/knowledge/{entry}/take-back-guesses").status_code == 409
