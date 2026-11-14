"""The place, the repeat and the role of an entry the app keeps itself can be changed after it is added (S-0101, with
S-0103's role): one change of the person's own with Undo, only what differs, a new repeat starts clean, a connected
calendar's entry is never edited here, and an assistant's `event.add` can't set a role."""

from __future__ import annotations

import pytest

from engine import add_meeting
from engine.applier import undo
from engine.storage import StoreError
from tests.test_add_meeting import entries, env  # noqa: F401  (fixture and helper)


def made(env, **more):  # noqa: F811
    _, cfg, store = env
    out = add_meeting.add_meeting(store, cfg, "Print sync", "2026-10-16", "15:00", **more)
    return cfg, store, out.entry


def now(store, entry):
    return store.read().get("event", entry)


def edit(cfg, store, entry, **fields):
    found = now(store, entry)
    args = {"where": found.data.get("where"), "repeat": None, "repeat_until": None, "role": found.data.get("role")}
    if found.data.get("repeat"):
        args["repeat"], args["repeat_until"] = found.data["repeat"]["every"], found.data["repeat"]["until"]
    return add_meeting.edit_entry(store, cfg, entry, found.version, **{**args, **fields})


def test_a_place_and_a_repeat_are_added_to_an_entry_afterwards_in_one_change_that_undo_reverses(env):  # noqa: F811
    cfg, store, entry = made(env)
    change = edit(cfg, store, entry, where="  Room 4 ", repeat="week", repeat_until="2026-12-18")
    data = now(store, entry).data
    assert data["where"] == "Room 4" and data["repeat"] == {"every": "week", "until": "2026-12-18"}
    undo(store, change)
    back = now(store, entry).data
    assert back.get("where") is None and back.get("repeat") is None


def test_nothing_changes_when_nothing_differs_and_an_empty_place_or_repeat_clears_it(env):  # noqa: F811
    cfg, store, entry = made(env, where="Room 4", repeat="week")
    assert edit(cfg, store, entry) is None
    assert edit(cfg, store, entry, where="", repeat=None) is not None
    data = now(store, entry).data
    assert data.get("where") is None and data.get("repeat") is None


def test_a_new_repeat_drops_the_moved_dates_of_the_old_one(env):  # noqa: F811
    cfg, store, entry = made(env, repeat="week")
    with store.transaction() as tx:
        from engine.storage import WriteContext

        tx.update(
            "event",
            entry,
            {"exceptions": [{"was": "2026-10-23T15:00:00", "cancelled": True}]},
            WriteContext("pm", "trusted", "test"),
            read_version=tx.get("event", entry).version,
        )
    edit(cfg, store, entry, repeat="day")
    assert now(store, entry).data["exceptions"] == []


def test_a_last_day_before_the_first_or_without_a_repeat_is_refused_in_words(env):  # noqa: F811
    cfg, store, entry = made(env)
    with pytest.raises(StoreError, match="before it starts"):
        edit(cfg, store, entry, repeat="week", repeat_until="2026-10-01")
    with pytest.raises(StoreError, match="how often"):
        edit(cfg, store, entry, repeat_until="2026-12-01")
    with pytest.raises(StoreError, match="from the list"):
        edit(cfg, store, entry, role="boss")


def test_an_entry_read_since_is_refused_and_a_connected_calendars_entry_is_not_edited_here(env):  # noqa: F811
    cfg, store, entry = made(env)
    with pytest.raises(StoreError, match="changed while"):
        add_meeting.edit_entry(store, cfg, entry, 99, "Room", None, None, None)
    with store.transaction() as tx:
        from engine.storage import WriteContext

        other = tx.create(
            "event",
            {"title": "Kept", "start": "2026-10-16", "key": "k", "source": "SRC-1", "trust": "trusted"},
            WriteContext("pm", "trusted", "test"),
        ).id
    with pytest.raises(StoreError, match="connected calendar"):
        add_meeting.edit_entry(store, cfg, other, 1, "Room", None, None, None)


def test_the_role_is_the_persons_to_set_and_the_assistants_event_add_cannot(env):  # noqa: F811
    cfg, store, entry = made(env, role="run")
    assert now(store, entry).data["role"] == "run"
    from engine.applier import Context, Inputs, apply_changeset
    from engine.names import People
    from engine.ops import CHANGESET
    from tests.test_knowledge_records import request as make_request

    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        tuple(store.plugins.ops),
        Inputs(make_request(store, "input", task="notes"), None, "", "Standup at nine", "untrusted"),
    )
    cs = CHANGESET.validate_python(
        {
            "ops": [
                {
                    "op": "event.add",
                    "title": "Standup",
                    "start": "2026-10-20T09:00:00+00:00",
                    "role": "brief_only",
                    "evidence": {"quote": "Standup at nine"},
                }
            ]
        },
        context={"op_models": store.plugins.ops},
    )
    from engine.applier import check

    problems = check(cs, ctx)
    assert any("only you say" in p.message for p in problems)
    del apply_changeset
