"""Every press that starts or approves work answers at once while a long reading of a source is under way (S-0677):
nothing waits on the reading's lock, and nothing runs the reading's own work inside the request. "At once" is proven by
order, not by the clock: each press answers while the reading still holds its lock, which a press that waited behind it
never could, and a press still waiting after a few seconds is reported as waiting."""

from __future__ import annotations

import threading
import time

import pytest

from engine import watch
from tests.test_handled import app, get, row  # noqa: F401  (the fixture)

ANSWER_WITHIN = 1.0


def press(client, path, body=None):
    """Make the press on a thread of its own, so a press that waits behind the reading is reported, not hung on."""
    out: dict = {}

    def run():
        began = time.monotonic()
        out["response"] = client.post(path, json=body) if body is not None else client.post(path)
        out["seconds"] = time.monotonic() - began
        # The reading still holds its lock: the answer came without waiting for it.
        out["during_reading"] = not getattr(client, "release_reading", threading.Event()).is_set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(ANSWER_WITHIN * 3)
    return out


@pytest.fixture
def reading(app):  # noqa: F811
    """A long reading of the source: its read lock is held by another thread until the test ends."""
    ws, cfg, store, client, base = app
    held, release = threading.Event(), threading.Event()

    def long_read():
        with watch._read_lock(ws, "m"):
            held.set()
            release.wait(30)

    thread = threading.Thread(target=long_read, daemon=True)
    thread.start()
    assert held.wait(5)
    # The worker's jobs loop is running, as it is for a person (the app is built without starting the worker).
    worker = client.app.state.worker
    loop = threading.Thread(target=release.wait, args=(30,), daemon=True)
    loop.start()
    worker._jobs = loop
    client.release_reading = release
    yield app
    release.set()
    thread.join(5)
    loop.join(5)
    worker._jobs = None


def answered(out):
    assert "seconds" in out, "the press was still waiting behind the reading"
    assert out["during_reading"], "the press answered only once the reading had ended"
    return out["response"]


def test_read_now_and_check_now_answer_at_once_during_a_reading(reading):
    ws, cfg, store, client, base = reading
    assert answered(press(client, f"{base}/watch/m/read")).status_code == 200
    assert answered(press(client, f"{base}/today/arrived/check")).status_code == 200


def test_hand_in_recent_answers_at_once_during_a_reading(reading):
    ws, cfg, store, client, base = reading
    assert answered(press(client, f"{base}/watch/m/recent")).status_code == 200


def test_treat_as_work_on_mail_read_with_nothing_to_do_answers_at_once_during_a_reading(reading):
    ws, cfg, store, client, base = reading
    item = row(get(client, base, tab="read"), "Lunch is moved")
    out = press(client, f"{base}/handled/{item['id']}/work", {"read_version": item["version"]})
    assert answered(out).status_code == 200


def test_treat_as_work_on_set_aside_mail_answers_at_once_during_a_reading(reading):
    ws, cfg, store, client, base = reading
    item = row(get(client, base, tab="set_aside"), "Sale sale-a")
    out = press(client, f"{base}/handled/{item['id']}/work", {"read_version": item["version"]})
    assert answered(out).status_code == 200


GOS = [
    ("/watch/m/intake/go", None),
    ("/runs/first-go", None),
    ("/setup/first-promises/go", None),
    ("/knowledge/catch-up/go", None),
    ("/watch/m/full-read", {"days": 30}),
    ("/watch/m/look-back", {"days": 30}),
    ("/watch/m/older-read/continue", None),
    ("/week-ahead/read", None),
]


@pytest.mark.parametrize(("path", "body"), GOS)
def test_each_start_or_go_answers_within_a_second_during_a_reading(reading, path, body):
    """The answer may be that there is nothing to start; it is never a wait, and never a failure of the server."""
    ws, cfg, store, client, base = reading
    response = answered(press(client, f"{base}{path}", body))
    assert response.status_code < 500, response.text


def test_a_go_on_a_held_request_answers_within_a_second_during_a_reading(reading):
    ws, cfg, store, client, base = reading
    with store.transaction() as tx:
        made = tx.create(
            "request",
            {
                "task": "ask",
                "state": "needs_you",
                "approval": "required",
                "waiting": "w",
                "origin": "pm",
                "created_at": store.clock(),
            },
            watch._WATCHER,
        )
    version = store.read().get("request", made.id).version
    response = answered(press(client, f"{base}/requests/{made.id}/go", {"read_version": version}))
    assert response.status_code in (200, 409), response.text
    assert answered(press(client, f"{base}/requests/{made.id}/retry")).status_code in (200, 409)


def test_the_recent_past_is_handed_in_once_the_reading_ends(reading):
    """The press only recorded the word: the worker's thread waited for the reading and then did the hand-in."""
    ws, cfg, store, client, base = reading
    worker = client.app.state.worker
    answered(press(client, f"{base}/watch/m/recent"))
    (asked,) = [t for t in worker._asks_apart if t.is_alive()]
    client.release_reading.set()
    asked.join(10)
    assert not asked.is_alive()


def test_check_the_synced_folder_now_answers_at_once_while_a_write_of_it_runs(reading, tmp_path):
    """The folder's pass waits for the pass that is writing; the press doesn't (nothing else is held but its lock)."""
    ws, cfg, store, client, base = reading
    worker = client.app.state.worker
    cfg.storage.sync.folder = str(tmp_path / "synced")
    asked = threading.Event()
    real = worker.sync_if_changed
    worker.sync_if_changed = lambda: (asked.set(), real())[1]
    with worker._sync_lock:
        assert answered(press(client, f"{base}/sync/check")).status_code == 200
        assert asked.wait(5), "the pass was asked for"
