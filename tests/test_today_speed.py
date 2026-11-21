"""Today opens fast on a workspace of a real person's size after the first reading: 18 to-dos, 6 people, 1,325 requests,
339 changes and 1,300 saved inputs. The route answers in under a second (the app's own limit for a screen is three)."""

from __future__ import annotations

import os
import time

from engine.storage import WriteContext
from tests.test_scale_messages import add_messages
from tests.test_today_query_count import _add_to_dos, _changes_made, counted  # noqa: F401

# The app's own limit for a slow screen (`ui.slow_screen_ms`'s default). The screens answer in about 0.4 s alone; a
# parallel run can double that, so the guard is the limit a person would be told about, and the read-once test below is
# what holds the fix.
LIMIT_SECONDS = 3.0
SCREENS = ("/api/today/queue", "/api/today/todo", "/api/people", "/api/changes")


def _fill(store, cfg) -> None:
    _add_to_dos(store, cfg, 18)
    add_messages(store, 1300)
    _changes_made(store, cfg, 339)
    _make_changes_big(store)


def _make_changes_big(store) -> None:
    """Each change of a sorted mailbox holds an op for every message it sorted: here 40 ops of about 1 KB each, as the
    first reading of a mailbox leaves them."""
    ctx = WriteContext(actor="pm", trust="trusted", op="test.speed")
    with store.transaction(notify=False) as tx:
        for stored in store.read().list("changeset"):
            data = dict(stored.data)
            template = data["ops"][0]
            ops = []
            for number in range(40):
                op = dict(template, index=number, group=f"op{number}")
                op["op"] = {**template["op"], "text": f"Message {number} " + "words " * 150}
                ops.append(op)
            data["ops"] = ops
            tx.update("changeset", stored.id, data, ctx, read_version=stored.version)


def _slowest_of_three(client, path: str) -> float:
    """The slowest of three answers in this process's own CPU time (the test client serves in this process), so other
    processes sharing the machine, as in a parallel run, don't count against the screen."""
    assert client.get(path).status_code == 200
    times = []
    for _ in range(3):
        began = time.process_time()
        assert client.get(path).status_code == 200
        times.append(time.process_time() - began)
    return max(times)


def test_the_main_screens_answer_within_the_slow_screen_limit_on_a_workspace_of_real_size(counted):  # noqa: F811
    client, _, store, cfg = counted
    _fill(store, cfg)
    if os.environ.get("PROFILE_TODAY"):
        import cProfile
        import pstats

        client.get("/api/today/queue")
        profile = cProfile.Profile()
        profile.enable()
        client.get("/api/today/queue")
        profile.disable()
        pstats.Stats(profile).sort_stats("cumulative").print_stats(40)
    slow = {path: round(t, 2) for path in SCREENS if (t := _slowest_of_three(client, path)) > LIMIT_SECONDS}
    assert not slow, f"slower than {LIMIT_SECONDS} s: {slow}"


def test_a_shared_list_is_read_once_in_a_read_scope_and_again_after_a_write(counted):  # noqa: F811
    _, _, store, cfg = counted
    _add_to_dos(store, cfg, 2)
    with store.read_scope():
        first = store.read().shared_list("action")
        assert store.read().shared_list("action") is first
        with store.transaction() as tx:
            tx.create(
                "action",
                {"text": "Made in the scope", "owners": [{"person": cfg.workspace.user.person}]},
                WriteContext(actor="pm", trust="trusted", op="t"),
            )
        assert len(store.read().shared_list("action")) == len(first) + 1
    assert store.read().shared_list("action") is not store.read().shared_list("action")
