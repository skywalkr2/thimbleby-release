"""The app applies a waiting lesson itself, as a marked guess (S-0861, the #74 re-check, row 11): when an assistant's
change leaves an open to-do owned by the person alone on a project a not-yet-kept lesson or routing entry applies to,
one small `guess-fit` request is queued in the same transaction; the run decides whether the to-do is that kind of
work and hands it to the person the entry names, marked as a guess with who owed it, or leaves it. Names and ids come
from the fixtures; the AI is the stub."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from engine import guess_fit
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.applier import Context, Inputs, apply_as_person, check
from engine.dispatcher import process
from engine.intake import hand_in
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, without_first_go

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
_TEST = WriteContext("engine", "trusted", "test")


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    without_first_go(ws.config_dir)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield ws, cfg, store
    store.close()
    set_responder(None)


def _project(store, nth: int = 0):
    return store.read().list("project")[nth]


def _other(store, cfg, *, not_this: str | None = None) -> str:
    me = People(store, cfg).pm
    return next(p.id for p in store.read().list("person") if p.id not in (me, not_this) and p.data.get("full_name"))


def waiting_entry(store, cfg, project, *, person: str | None = None, status: str = "proposed", kind="routing") -> str:
    """What the person's correction taught for a project's kind of work, waiting for their Keep."""
    who = person or _other(store, cfg)
    name = store.read().get("person", who).data["full_name"]
    kind_of_work = f"what goes out for {project.data['name']}"
    common = {
        "text": f"What goes out for {project.data['name']} is {name}'s to send.",
        "kind_of_work": kind_of_work,
        "origin": "assistant",
        "status": status,
        "guess_until_kept": True,
        "learned_at": "2026-11-19T09:00:00+00:00",
        "applies_to": {},
    }
    record, extra = ("lesson", {}) if kind == "lesson" else ("routing_entry", {"topic": kind_of_work, "person": who})
    with store.transaction() as tx:
        entry = tx.create(record, {**common, **extra, "status": "proposed"}, _TEST).id
    if status != "proposed":
        set_status(store, cfg, record, entry, status)
    return entry


def set_status(store, cfg, record: str, entry: str, status: str) -> None:
    """The person keeps or discards a waiting entry."""
    kept = {"kept_by": People(store, cfg).pm, "kept_at": "2026-11-20T09:00:00+00:00"}
    fields = {"status": "active", **kept} if status == "active" else {"status": status, "discard_reason": "No."}
    with store.transaction() as tx:
        current = tx.get(record, entry)
        tx.update(record, entry, fields, _TEST, read_version=current.version)


def letters_note(project) -> str:
    return f"We also need to send the {project.data['name']} sponsor letters."


def add_letters(project, owners: list[str], note: str) -> dict:
    return {
        "summary": "Added the letters.",
        "ops": [
            {
                "op": "action.add",
                "text": f"Send the {project.data['name']} sponsor letters",
                "owners": owners,
                "project": project.id,
                "evidence": {"quote": note},
            }
        ],
    }


def answering(*bodies: dict) -> list:
    """The stub answers these in turn (the last repeats), and records what it was asked."""
    asked: list = []
    queue = [json.dumps(b) for b in bodies]

    def responder(task):
        asked.append(task)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    set_responder(responder)
    return asked


def run_request(env, request_id: str):
    ws, cfg, store = env
    return process(ws, store, cfg, Router(cfg, store, env={}), request_id, now=NOW)


def note_run(env, answer: dict, note: str) -> str:
    """Hand in the person's note and let the assistant answer it with `answer`: the changeset id."""
    ws, cfg, store = env
    answering(answer)
    request = hand_in(ws, store, note=note, pasted="", now=NOW).request
    return run_request(env, request)


def guess_fits(store) -> list:
    return [r for r in store.read().list("request") if r.data["task"] == guess_fit.TASK]


def made_action(store, cs_id: str) -> str:
    return next(r["id"] for o in store.read().get("changeset", cs_id).data["ops"] for r in o["records"])


def owners_of(store, action_id: str) -> list[str]:
    return [o["person"] for o in store.read().get("action", action_id).data["owners"]]


# ---- queuing -------------------------------------------------------------------------------------------------------


def test_a_to_do_a_note_gives_the_person_on_a_waiting_entrys_project_queues_one_guess_check(env):
    ws, cfg, store = env
    project = _project(store)
    entry = waiting_entry(store, cfg, project)
    me = People(store, cfg).pm
    cs_id = note_run(env, add_letters(project, [me], letters_note(project)), letters_note(project))
    action = made_action(store, cs_id)
    (queued,) = guess_fits(store)
    assert queued.data["pairs"] == [{"action": action, "entry": entry}]
    assert queued.data["follows"] == cs_id and queued.data["about"] == {"kind": "action", "id": action}
    assert (queued.data["state"], queued.data["origin"]) == ("queued", "schedule")


def test_a_lesson_that_names_someone_in_its_words_is_paired_like_a_routing_entry(env):
    ws, cfg, store = env
    project = _project(store)
    entry = waiting_entry(store, cfg, project, kind="lesson")
    me = People(store, cfg).pm
    cs_id = note_run(env, add_letters(project, [me], letters_note(project)), letters_note(project))
    (queued,) = guess_fits(store)
    assert queued.data["pairs"] == [{"action": made_action(store, cs_id), "entry": entry}]


@pytest.mark.parametrize(
    "case",
    [
        "setting-off",
        "went-to-someone-else",
        "entry-kept",
        "entry-discarded",
        "entry-names-the-person",
        "another-project",
        "a-guess-check-run-is-never-followed",
    ],
)
def test_no_guess_check_is_queued_unless_everything_holds(env, case):
    ws, cfg, store = env
    project = _project(store)
    me = People(store, cfg).pm
    other = _other(store, cfg)
    owners = [other] if case == "went-to-someone-else" else [me]
    status = {"entry-kept": "active", "entry-discarded": "discarded"}.get(case, "proposed")
    person = me if case == "entry-names-the-person" else None
    entry_project = _project(store, 1) if case == "another-project" else project
    if case == "setting-off":
        cfg = ws.config(env={}, flags={"dispatch.knowledge.apply_guesses": False})
        store.plugins.cfg = cfg
        env = (ws, cfg, store)
    entry = waiting_entry(store, cfg, entry_project, person=person, status=status)
    if case == "a-guess-check-run-is-never-followed":
        note_run(env, add_letters(project, [me], letters_note(project)), letters_note(project))
        (first,) = guess_fits(store)
        answering({"summary": "Handed it over.", "ops": [], "by_kind": []})
        run_request(env, first.id)
        assert [r.id for r in guess_fits(store)] == [first.id]
        return
    note_run(env, add_letters(project, owners, letters_note(project)), letters_note(project))
    assert guess_fits(store) == [], entry


def test_the_persons_own_change_on_screen_is_never_second_guessed(env):
    ws, cfg, store = env
    project = _project(store)
    waiting_entry(store, cfg, project)
    me = People(store, cfg).pm
    words = "Send the sponsor letters"
    add = {
        "op": "action.add",
        "text": words,
        "owners": [me],
        "project": project.id,
        "evidence": {"quote": words},
    }
    apply_as_person(store, cfg, [add], "Added on screen", note=words)
    assert guess_fits(store) == []


def test_a_to_do_already_marked_as_a_guess_is_not_paired(env):
    ws, cfg, store = env
    project = _project(store)
    entry = waiting_entry(store, cfg, project)
    me = People(store, cfg).pm
    with store.transaction() as tx:
        marked = tx.create(
            "action",
            {
                "text": "Send the sponsor letters",
                "owners": [{"person": me}],
                "project": project.id,
                "status": "open",
                "by_kind": {
                    "entry": entry,
                    "kind_of_work": "what goes out",
                    "learned_on": "2026-11-19",
                    "owners_before": [me],
                },
            },
            _TEST,
        )
        plain = tx.create(
            "action",
            {"text": "Send the other letters", "owners": [{"person": me}], "project": project.id, "status": "open"},
            _TEST,
        )
    pairs, _ = guess_fit.pairs_for(store.read(), cfg, [marked.id, plain.id])
    assert pairs == [{"action": plain.id, "entry": entry}]


def test_a_stood_down_queue_logs_its_reason_by_ids_only(env, caplog):
    ws, cfg, store = env
    project = _project(store)
    me = People(store, cfg).pm
    entry = waiting_entry(store, cfg, project, person=me)
    with caplog.at_level(logging.WARNING, logger="engine.guess_fit"):
        cs_id = note_run(env, add_letters(project, [me], letters_note(project)), letters_note(project))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("guess fit:")]
    assert lines and made_action(store, cs_id) in lines[0]
    assert "sponsor" not in " ".join(lines) and project.data["name"] not in " ".join(lines)
    assert entry not in guess_fits(store) and guess_fits(store) == []
    caplog.clear()
    cfg_off = ws.config(env={}, flags={"dispatch.knowledge.apply_guesses": False})
    store.plugins.cfg = cfg_off
    other_entry = waiting_entry(store, cfg, project)
    with caplog.at_level(logging.WARNING, logger="engine.guess_fit"):
        note_run((ws, cfg_off, store), add_letters(project, [me], "Send more letters."), "Send more letters.")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("guess fit:")]
    assert lines and other_entry in lines[0] and "switched off" in lines[0] and "letters" not in lines[0]


# ---- the run ------------------------------------------------------------------------------------------------------


def queued_check(env):
    """The person's note gives them the letters on a waiting entry's project: the entry, the person it names, the
    to-do's id and the queued request."""
    ws, cfg, store = env
    project = _project(store)
    entry = waiting_entry(store, cfg, project)
    me = People(store, cfg).pm
    cs_id = note_run(env, add_letters(project, [me], letters_note(project)), letters_note(project))
    (queued,) = guess_fits(store)
    return project, entry, store.read().get("routing_entry", entry).data["person"], made_action(store, cs_id), queued


def test_the_to_do_goes_to_the_entrys_person_marked_as_a_guess_and_taking_it_back_restores_the_person(env):
    ws, cfg, store = env
    project, entry, who, action, queued = queued_check(env)
    me = People(store, cfg).pm
    asked = answering(
        {
            "summary": "Handed the letters over.",
            "ops": [
                {
                    "op": "action.owners",
                    "id": action,
                    "owners": [who],
                    "evidence": {"quote": store.read().get("routing_entry", entry).data["text"]},
                }
            ],
            "by_kind": [{"op": 0, "entry": entry}],
        }
    )
    assert run_request(env, queued.id) is not None
    assert owners_of(store, action) == [who]
    mark = store.read().get("action", action).data["by_kind"]
    assert mark["entry"] == entry and mark["owners_before"] == [me]
    # The run asked once, in its own packet: the to-do, the entry's kind of work and its words, and the person's name.
    assert len(asked) == 1 and asked[0].kind == guess_fit.TASK
    request = asked[0].request
    assert action in request and store.read().get("routing_entry", entry).data["kind_of_work"] in request
    assert store.read().get("person", who).data["full_name"] in request
    # One hop: its own change queued nothing.
    assert [r.id for r in guess_fits(store)] == [queued.id]
    apply_as_person(store, cfg, [{"op": "action.owners", "id": action, "owners": [me]}], "Took back a guess")
    assert owners_of(store, action) == [me] and store.read().get("action", action).data.get("by_kind") is None


def test_a_hand_over_the_run_did_not_name_is_still_marked_as_a_guess(env):
    ws, cfg, store = env
    project, entry, who, action, queued = queued_check(env)
    answering(
        {
            "summary": "Handed the letters over.",
            "ops": [
                {
                    "op": "action.owners",
                    "id": action,
                    "owners": [who],
                    "evidence": {"quote": store.read().get("routing_entry", entry).data["text"]},
                }
            ],
        }
    )
    run_request(env, queued.id)
    assert store.read().get("action", action).data["by_kind"]["entry"] == entry


def test_with_no_hand_over_the_to_do_stays_the_persons_and_nothing_changes(env):
    ws, cfg, store = env
    project, entry, who, action, queued = queued_check(env)
    me = People(store, cfg).pm
    answering({"summary": "Nothing here is that kind of work.", "ops": [], "by_kind": []})
    run_request(env, queued.id)
    assert owners_of(store, action) == [me] and store.read().get("action", action).data.get("by_kind") is None
    closed = store.read().get("request", queued.id).data
    assert closed["state"] == "done" and closed["waiting"] == guess_fit.NOTHING_FIT
    assert guess_fit.closed_quietly(closed)


def test_a_pair_that_no_longer_stands_closes_with_no_call(env):
    ws, cfg, store = env
    project, entry, who, action, queued = queued_check(env)
    set_status(store, cfg, "routing_entry", entry, "active")
    asked = answering({"summary": "unused", "ops": []})
    assert run_request(env, queued.id) is None
    assert asked == [] and store.read().get("request", queued.id).data["waiting"] == guess_fit.NOTHING_TO_CHECK
    assert [r.data["task"] for r in store.read().list("run")] == ["notes"]  # the one that made the to-do, no other


def test_a_hand_over_a_guess_check_makes_is_not_held_as_outside_content(env):
    """The run reads only the person's own lesson and their to-do, so its hand-over applies at once (with Undo) and is
    not held with "Outside content says someone else owes this now"."""
    ws, cfg, store = env
    project, entry, who, action, queued = queued_check(env)
    answering(
        {
            "summary": "Handed over.",
            "ops": [
                {
                    "op": "action.owners",
                    "id": action,
                    "owners": [who],
                    "evidence": {"quote": store.read().get("routing_entry", entry).data["text"]},
                }
            ],
            "by_kind": [{"op": 0, "entry": entry}],
        }
    )
    cs_id = run_request(env, queued.id)
    assert [o["status"] for o in store.read().get("changeset", cs_id).data["ops"]] == ["applied"]
    assert store.read().get("changeset", cs_id).data["trust"] == "trusted"


# ---- the answer's checks --------------------------------------------------------------------------------------------


def _ctx(env, request_id: str) -> Context:
    ws, cfg, store = env
    return Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(request_id, None, "", "", "trusted", cites=f"guess-fit:{request_id}"),
    )


def _refusals(env, request_id: str, answer: dict) -> list[str]:
    _, _, store = env
    cs = CHANGESET.validate_python(answer, context={"op_models": store.plugins.ops})
    return [p.message for p in check(cs, _ctx(env, request_id)) if p.check == "guess-fit-reach"]


def test_the_check_refuses_a_hand_over_to_anyone_else_or_of_another_to_do_or_naming_another_entry(env):
    ws, cfg, store = env
    project, entry, who, action, queued = queued_check(env)
    me = People(store, cfg).pm
    stranger = _other(store, cfg, not_this=who)
    quote = {"quote": store.read().get("routing_entry", entry).data["text"]}
    with store.transaction() as tx:
        elsewhere = tx.create(
            "action",
            {"text": "Water the plants", "owners": [{"person": me}], "project": project.id, "status": "open"},
            _TEST,
        ).id
    other_entry = waiting_entry(store, cfg, _project(store, 1))

    def hand(to_do: str, to: str, **extra) -> dict:
        return {"ops": [{"op": "action.owners", "id": to_do, "owners": [to], "evidence": quote}], **extra}

    assert _refusals(env, queued.id, hand(action, who, by_kind=[{"op": 0, "entry": entry}])) == []
    assert _refusals(env, queued.id, hand(action, stranger))
    assert _refusals(env, queued.id, hand(elsewhere, who))
    assert _refusals(env, queued.id, hand(action, who, by_kind=[{"op": 0, "entry": other_entry}]))
    assert _refusals(env, queued.id, {"ops": [{"op": "note", "text": "hello"}]})


def test_a_to_do_the_person_took_themselves_in_their_own_note_is_never_offered_to_a_guess(env, caplog):
    """The #75 plan's review (2): "I'll send the gala sponsor thank-you letters myself." must stay the person's. The
    check reads the stored to-do, so it also reads the person's own words it came from: a sentence where they promise
    it themselves takes the to-do out of the check, and the log says so by ids only. The same to-do said with "We need
    to" is still checked, and the packet carries the person's sentence for the model to read."""
    import logging

    from engine.packet import build as build_packet

    ws, cfg, store = env
    project = _project(store)
    waiting_entry(store, cfg, project)
    me = People(store, cfg).pm
    mine = f"I'll send the {project.data['name']} sponsor letters myself."
    with caplog.at_level(logging.WARNING, logger="engine.guess_fit"):
        cs_id = note_run(env, add_letters(project, [me], mine), mine)
    action = made_action(store, cs_id)
    assert owners_of(store, action) == [me] and guess_fits(store) == []
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("guess fit:")]
    assert lines == [f"guess fit: {action} taken by the person in their own note"]
    ours = letters_note(project)
    note_run(env, add_letters(project, [me], ours), ours)
    (queued,) = guess_fits(store)
    packet = build_packet(ws, store, cfg, queued.id, NOW.date())
    assert f"Your own words when this to-do came in: {ours}" in packet.task.request
