"""The main screens' time budget (design 6.13): a main screen slower than `server.slow_screen_ms` three loads in a
row is one Today line that offers a report, three fast loads clear it, the report holds counts and names no one, and
a write finishes while a long read is open."""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine import slow_screens
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

TOKEN = "slow-screens-token"
_TEST = WriteContext(actor="pm", trust="trusted", op="test.slow-screens")


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "server.slow_screen_ms": 100})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, ws, cfg, app.state.store


def lines(client):
    return [x for x in client.get("/api/today/queue").json() if x["kind"] == "slow_screen"]


def test_three_slow_loads_in_a_row_make_one_line_and_three_fast_ones_clear_it(env):
    client, ws, cfg, _ = env
    found = slow_screens.for_workspace(ws.root)
    found.note("/api/people", 5000)
    found.note("/api/people", 5000)
    assert lines(client) == []
    found.note("/api/people", 4200)
    (line,) = lines(client)
    assert line["subject"] == "people" and line["seconds"] == 4.2
    found.note("/api/people", 5000)
    assert len(lines(client)) == 1  # still one line, not one per load
    found.note("/api/people", 10)
    found.note("/api/people", 10)
    assert len(lines(client)) == 1  # two fast loads are not yet three
    found.note("/api/people", 10)
    assert lines(client) == []


def test_one_fast_load_among_slow_ones_breaks_the_run(env):
    client, ws, *_ = env
    found = slow_screens.for_workspace(ws.root)
    for ms in (5000, 5000, 10, 5000, 5000):
        found.note("/api/changes", ms)
    assert lines(client) == []


def test_a_route_that_is_not_a_main_screen_is_logged_and_never_a_line(env, caplog):
    client, ws, *_ = env
    found = slow_screens.for_workspace(ws.root)
    with caplog.at_level(logging.INFO, logger="engine.slow_screens"):
        for _ in range(4):
            found.note("/api/sources", 9000)
    assert lines(client) == [] and "/api/sources" in caplog.text


def test_a_real_slow_request_is_timed_with_its_route_and_counts_toward_its_screen(env, monkeypatch):
    client, ws, *_ = env
    clock = iter(x * 1.0 for x in range(10_000))  # every reading is a second later: each request "takes" seconds
    monkeypatch.setattr("api.app.time", SimpleNamespace(perf_counter=lambda: next(clock)))
    for _ in range(3):
        assert client.get("/api/people").status_code == 200
    assert "people" in slow_screens.for_workspace(ws.root).slow()


def test_the_report_holds_the_screen_the_time_the_limit_and_counts_and_names_no_one(env):
    client, ws, cfg, store = env
    assert client.get("/api/slow-screens/people/report").status_code == 404  # not slow now
    with store.transaction() as tx:
        tx.create("person", {"full_name": "Zed Quillfeather"}, _TEST)
    found = slow_screens.for_workspace(ws.root)
    for _ in range(3):
        found.note("/api/people", 4000)
    body = client.get("/api/slow-screens/people/report").json()
    assert "People" in body["title"]
    assert "4.0 seconds" in body["text"] and "0.1 seconds" in body["text"] and "person" in body["text"]
    assert "Zed" not in body["text"] and "Quillfeather" not in body["text"]


def test_a_write_finishes_while_a_long_read_is_open(env):
    """WAL and one connection per thread: a reader holding a read open never makes a writer wait."""
    _, _, _, store = env
    reading, release, done = threading.Event(), threading.Event(), threading.Event()
    failed: list[BaseException] = []

    def long_read():
        try:
            with store.read_scope():
                store.read().list("person")
                conn = store._conn
                conn.execute("BEGIN")
                conn.execute("SELECT count(*) FROM records").fetchall()  # a read transaction held open
                reading.set()
                release.wait(10)
                conn.execute("COMMIT")
        except BaseException as exc:  # noqa: BLE001
            failed.append(exc)
            reading.set()

    thread = threading.Thread(target=long_read)
    thread.start()
    assert reading.wait(10)

    def write():
        with store.transaction() as tx:
            tx.create("person", {"full_name": "Written During A Read"}, _TEST)
        done.set()

    writer = threading.Thread(target=write)
    writer.start()
    finished = done.wait(5)
    release.set()
    thread.join()
    writer.join()
    assert not failed, failed
    assert finished, "the write waited for the open read"
