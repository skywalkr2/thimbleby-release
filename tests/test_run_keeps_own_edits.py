"""A run writes only its own changes (S-0327, part B): an edit the person makes after a run has read a record is kept.

Each case hands the assistant the person's own note, and while the assistant is answering (after the packet was built
from the records) the person edits the record the answer is about. The answer then applies. Today every op on an
existing record is checked against the version current when it applies, so it lands over the edit. The cases are
strict expected failures until the fix is designed; names and ids come from the fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.applier import apply_as_person, decline_held, release, undo
from engine.dispatcher import parse, process
from engine.intake import hand_in
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_corrections import pm_of

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
BY_PERSON = "Changed by the person"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()
    set_responder(None)


def run_over_an_edit(
    env, note: str, answer: list[dict], edit: list[dict], reads: tuple[str, ...] = (), extra_keys: dict | None = None
):
    """The person's note is handed in; while the answer is made the person applies `edit`; then the answer applies.
    Returns the changeset id and what the model was asked."""
    ws, cfg, store = env
    extra_keys = extra_keys or {}
    tasks: list = []

    def responder(task):
        tasks.append(task)
        if len(tasks) == 1 and edit:
            apply_as_person(store, cfg, edit, "The person's own edit", note=BY_PERSON)
        return json.dumps({"summary": "From the note.", "ops": answer, **extra_keys})

    set_responder(responder)
    handed = hand_in(ws, store, note=note, now=NOW)
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    assert cs_id is not None and tasks
    for record_id in reads:  # the run was shown the record before the person's edit
        assert record_id in tasks[0].stable + tasks[0].request
    return cs_id, tasks


_TEST = WriteContext(actor="pm", trust="trusted", op="test.run-edits")


def an_open_action(store):
    return next(a for a in store.read().list("action") if a.data.get("status", "open") == "open")


def an_event(store, title="Review meeting", **fields):
    with store.transaction() as tx:
        return tx.create("event", {"title": title, "start": "2026-11-03", "trust": "trusted", **fields}, _TEST)


def a_series(store, title):
    with store.transaction() as tx:
        return tx.create("series", {"title": title, "trust": "trusted"}, _TEST)


def quote(op: dict, words: str) -> dict:
    return {**op, "evidence": {"quote": words}}


def held_op(env, cs_id: str, name: str) -> dict:
    """The run's op `name`, which must be held for the person with the words that say they changed the record."""
    _, cfg, store = env
    found = [o for o in store.read().get("changeset", cs_id).data["ops"] if o["op"]["op"] == name]
    assert [o["status"] for o in found] == ["held"], [(o["status"], o.get("reason")) for o in found]
    assert f"You changed this while {cfg.workspace.assistant_name} was working on it." in found[0]["reason"]
    return found[0]


def kept(env, note, answer, edit, kind, record_id, field, wanted, holds=True):
    """Run the case, then check the field still holds what the person set and the run's op waits for the person."""
    _, _, store = env
    cs_id, _ = run_over_an_edit(env, note, answer, edit, reads=(record_id,))
    assert store.read().get(kind, record_id).data[field] == wanted
    if holds:
        held_op(env, cs_id, answer[0]["op"])


def test_a_run_moving_a_date_does_not_overwrite_the_persons_own_change(env):
    _, _, store = env
    target = an_open_action(store)
    words = "push it to the end of next month"
    kept(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.move", "id": target.id, "due": "2026-11-30"}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "due", "value": "2026-10-27"}],
        "action",
        target.id,
        "due",
        "2026-10-27",
    )


def test_a_run_setting_a_field_does_not_overwrite_the_persons_own_change(env):
    _, _, store = env
    target = an_open_action(store)
    words = "rewrite it as the shorter line"
    kept(
        env,
        f"{target.data['text']}: {words}",
        [
            quote(
                {"op": "record.set", "kind": "action", "id": target.id, "field": "text", "value": "Shorter line"}, words
            )
        ],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "text", "value": "The person's own words"}],
        "action",
        target.id,
        "text",
        "The person's own words",
    )


def test_a_run_putting_an_action_on_hold_does_not_overwrite_the_persons_own_hold(env):
    _, _, store = env
    target = an_open_action(store)
    words = "waiting for the printer"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.hold", "id": target.id, "waiting_for": "The printer"}, words)],
        [{"op": "action.hold", "id": target.id, "waiting_for": "The person's own wait"}],
        reads=(target.id,),
    )
    assert store.read().get("action", target.id).data["on_hold"]["waiting_for"] == "The person's own wait"
    held_op(env, cs_id, "action.hold")


def test_a_run_taking_an_action_off_hold_does_not_undo_the_persons_new_hold(env):
    _, _, store = env
    target = an_open_action(store)
    with store.transaction() as tx:
        tx.update(
            "action",
            target.id,
            {"on_hold": {"waiting_for": "The first wait", "since": "2026-10-01"}},
            _TEST,
            read_version=target.version,
        )
    words = "it arrived, carry on"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.unhold", "id": target.id}, words)],
        [{"op": "action.hold", "id": target.id, "waiting_for": "The person's own new wait"}],
        reads=(target.id,),
    )
    assert (store.read().get("action", target.id).data["on_hold"] or {}).get(
        "waiting_for"
    ) == "The person's own new wait"
    held_op(env, cs_id, "action.unhold")


def test_a_run_reporting_part_done_does_not_overwrite_the_persons_own_wording(env):
    _, _, store = env
    target = an_open_action(store)
    words = "half of it is done"
    kept(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.part", "id": target.id, "delivered": "Half", "left": "The other half"}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "text", "value": "The person's own words"}],
        "action",
        target.id,
        "text",
        "The person's own words",
    )


def test_a_run_tying_an_action_to_a_meeting_does_not_overwrite_the_persons_own_day(env):
    _, _, store = env
    target = an_open_action(store)
    meeting = an_event(store)
    words = "it goes with the review meeting"
    kept(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.tie", "id": target.id, "event": meeting.id}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "due", "value": "2026-10-27"}],
        "action",
        target.id,
        "due",
        "2026-10-27",
    )


def test_a_run_moving_a_meeting_does_not_overwrite_the_persons_own_time(env):
    _, _, store = env
    meeting = an_event(store)
    words = "the review meeting moves to the ninth"
    kept(
        env,
        words,
        [quote({"op": "event.set", "id": meeting.id, "start": "2026-11-09"}, words)],
        [{"op": "event.set", "id": meeting.id, "start": "2026-11-04", "evidence": {"quote": BY_PERSON}}],
        "event",
        meeting.id,
        "start",
        "2026-11-04",
    )


def test_a_run_linking_a_meeting_to_a_series_is_refused_when_the_person_linked_it_meanwhile(env):
    """Not a gap: the check at apply time refuses a link when the entry already belongs to another series."""
    _, _, store = env
    meeting = an_event(store)
    first, second = a_series(store, "Weekly review"), a_series(store, "Monthly review")
    words = "the review meeting is the weekly review"
    kept(
        env,
        words,
        [quote({"op": "series.link", "event": meeting.id, "series": first.id}, words)],
        [{"op": "series.link", "event": meeting.id, "series": second.id, "evidence": {"quote": BY_PERSON}}],
        "event",
        meeting.id,
        "series",
        second.id,
        holds=False,  # refused by its own precondition, not held
    )


def test_a_run_setting_a_stance_does_not_overwrite_the_persons_own_stance(env):
    _, cfg, store = env
    who = next(p for p in store.read().list("person") if p.id != pm_of(cfg))
    words = "treat them as someone you manage"
    kept(
        env,
        f"{who.data['full_name']}: {words}",
        [quote({"op": "person.stance", "id": who.id, "stance": "manage"}, words)],
        [{"op": "person.stance", "id": who.id, "stance": "alongside"}],
        "person",
        who.id,
        "stance",
        "alongside",
    )


def test_the_ledger_holds_only_the_persons_edit_and_the_runs_held_op_writes_nothing(env):
    """The person's edit is its own ledger entry; the run's op is held, so none of it is written to the field."""
    _, _, store = env
    target = an_open_action(store)
    words = "push it to the end of next month"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.move", "id": target.id, "due": "2026-11-30"}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "due", "value": "2026-10-27"}],
        reads=(target.id,),
    )
    rows = [e for e in store.read().ledger() if (e["kind"], e["record_id"], e["field"]) == ("action", target.id, "due")]
    assert (rows[-1]["actor"], rows[-1]["after"]) == ("pm", "2026-10-27") and rows[-1]["changeset"] != cs_id
    held_op(env, cs_id, "action.move")


def test_a_run_setting_how_an_action_repeats_does_not_overwrite_the_persons_own_day(env):
    _, _, store = env
    target = an_open_action(store)
    words = "every Monday"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.repeat", "id": target.id, "words": words}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "due", "value": "2026-10-26"}],
        reads=(target.id,),
    )
    assert store.read().get("action", target.id).data["due"] == "2026-10-26"
    assert store.read().get("action", target.id).data["repeat"] is None
    held_op(env, cs_id, "action.repeat")


def test_a_run_making_a_series_of_a_meeting_does_not_overwrite_the_persons_own_time(env):
    _, _, store = env
    meeting = an_event(store)
    words = "the review meeting is every week"
    cs_id, _ = run_over_an_edit(
        env,
        words,
        [quote({"op": "series.add", "title": "Weekly review", "events": [meeting.id]}, words)],
        [{"op": "event.set", "id": meeting.id, "start": "2026-11-04", "evidence": {"quote": BY_PERSON}}],
        reads=(meeting.id,),
    )
    kept_entry = store.read().get("event", meeting.id)
    assert kept_entry.data["start"] == "2026-11-04" and not kept_entry.data.get("series")
    assert not store.read().list("series")
    held_op(env, cs_id, "series.add")


def held_move(env):
    """A run's move of a date held over the person's own change: the changeset, the action and the held index."""
    _, _, store = env
    target = an_open_action(store)
    words = "push it to the end of next month"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.move", "id": target.id, "due": "2026-11-30"}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "due", "value": "2026-10-27"}],
        reads=(target.id,),
    )
    held = held_op(env, cs_id, "action.move")
    return cs_id, target, held["index"]


def test_apply_anyway_applies_the_held_op_as_the_persons_own_with_undo(env):
    ws, cfg, store = env
    cs_id, target, index = held_move(env)
    release(store, cfg, cs_id, index)
    assert store.read().get("action", target.id).data["due"] == "2026-11-30"
    last = [e for e in store.read().ledger() if (e["record_id"], e["field"]) == (target.id, "due")][-1]
    assert (last["actor"], last["changeset"]) == ("pm", cs_id)
    undo(store, cs_id)
    assert store.read().get("action", target.id).data["due"] == "2026-10-27"


def test_leave_it_keeps_the_persons_value_and_records_a_signal_for_the_knowledge_loop(env):
    _, _, store = env
    cs_id, target, index = held_move(env)
    decline_held(store, cs_id, index)
    assert store.read().get("action", target.id).data["due"] == "2026-10-27"
    (signal,) = [s for s in store.read().list("signal") if s.data["kind"] == "held_declined"]
    assert signal.data["changeset"] == cs_id and target.id in signal.data["refs"]


def test_a_run_changing_the_same_record_twice_does_not_hold_its_own_later_op(env):
    _, _, store = env
    target = an_open_action(store)
    other = next(a for a in store.read().list("action") if a.id != target.id)
    words = "push it to the end of next month and call it the shorter line"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [
            quote({"op": "action.move", "id": target.id, "due": "2026-11-30"}, words),
            quote(
                {"op": "record.set", "kind": "action", "id": target.id, "field": "text", "value": "Shorter line"}, words
            ),
        ],
        [{"op": "record.set", "kind": "action", "id": other.id, "field": "text", "value": "The person's own words"}],
        reads=(target.id,),
    )
    got = store.read().get("action", target.id).data
    assert (got["due"], got["text"]) == ("2026-11-30", "Shorter line")
    ops = store.read().get("changeset", cs_id).data["ops"]
    assert [o["status"] for o in ops] == ["applied", "applied"]


def test_a_model_answer_carrying_reads_is_ignored_and_the_op_is_still_held(env):
    _, _, store = env
    parsed = parse(json.dumps({"summary": "s", "ops": [], "reads": [["action", "ACT-1", 0]]}))
    assert parsed.ops == [] and not hasattr(parsed, "reads")
    target = an_open_action(store)
    words = "push it to the end of next month"
    cs_id, _ = run_over_an_edit(
        env,
        f"{target.data['text']}: {words}",
        [quote({"op": "action.move", "id": target.id, "due": "2026-11-30"}, words)],
        [{"op": "record.set", "kind": "action", "id": target.id, "field": "due", "value": "2026-10-27"}],
        reads=(target.id,),
        extra_keys={"reads": []},
    )
    assert store.read().get("action", target.id).data["due"] == "2026-10-27"
    held_op(env, cs_id, "action.move")


def test_every_op_says_whether_it_overwrites_an_existing_record():
    from engine.ops import NON_OVERWRITING_OPS, OP_MODELS, OVERWRITING_OPS

    assert not OVERWRITING_OPS & NON_OVERWRITING_OPS
    assert set(OP_MODELS) == OVERWRITING_OPS | NON_OVERWRITING_OPS


def test_a_run_changing_a_record_it_found_by_searching_is_held_when_the_person_changed_it_meanwhile(env):
    ws, cfg, store = env
    template = an_open_action(store)
    with store.transaction() as tx:
        found = tx.create(
            "action",
            {**template.data, "text": "Repaint the zebra crossing", "status": "done"},
            _TEST,
        )
    words = "call the zebra crossing job the lines task"
    tasks: list = []

    def responder(task):
        tasks.append(task)
        if len(tasks) == 1:
            return json.dumps({"search": {"words": "zebra crossing", "kinds": ["records"]}})
        if len(tasks) == 2:
            apply_as_person(
                store,
                cfg,
                [
                    {
                        "op": "record.set",
                        "kind": "action",
                        "id": found.id,
                        "field": "text",
                        "value": "The person's words",
                    }
                ],
                "The person's own edit",
                note=BY_PERSON,
            )
        answer = [
            quote({"op": "record.set", "kind": "action", "id": found.id, "field": "text", "value": "Lines task"}, words)
        ]
        return json.dumps({"summary": "From the note.", "ops": answer})

    set_responder(responder)
    handed = hand_in(ws, store, note=words, now=NOW)
    cs_id = process(ws, store, cfg, Router(cfg, store, env={}), handed.request, now=NOW)
    assert cs_id is not None and len(tasks) >= 2
    assert found.id not in tasks[0].stable + tasks[0].request  # the first packet did not show it: the search did
    assert store.read().get("action", found.id).data["text"] == "The person's words"
    held_op(env, cs_id, "record.set")
