"""The main screens stay fast with about 50,000 messages (about the mail of a few years): what a screen's request makes
the database do does not grow with the number of messages. Measured as work the database does (its virtual-machine
steps, counted by a progress handler, never timed), so a small machine can't fail it and a full scan can't hide in a
single query. The fixture is made in one transaction."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

TOKEN = "scale-token"
_TEST = WriteContext(actor="pm", trust="trusted", op="test.scale")

#: The progress handler runs once for this many virtual-machine steps.
STEP = 1000
FEW = 500
MANY = 50_000
#: What a screen's request may do beyond its work on the few: a fixed amount of steps, never a share of the messages.
GROWTH_CEILING = 40
SCREENS = ["/api/today/queue", "/api/today/todo", "/api/people", "/api/changes", "/api/schedule"]


class Work:
    """Counts the database's work per request while on, across the threads that run it."""

    def __init__(self) -> None:
        self.on = False
        self.ticks = 0
        self._lock = threading.Lock()

    def tick(self) -> int:
        if self.on:
            with self._lock:
                self.ticks += 1
        return 0


@pytest.fixture
def measured(tmp_path, monkeypatch):
    work = Work()
    import engine.storage.store as store_module

    real = store_module.connect

    def connect(path):
        conn = real(path)
        conn.set_progress_handler(work.tick, STEP)
        return conn

    monkeypatch.setattr(store_module, "connect", connect)
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/"})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, work, app.state.store, cfg


def add_messages(store: Store, count: int, first: int = 0) -> None:
    """`count` mail messages already dealt with, the newest a minute apart, in one transaction. Each is a snapshot (what
    the source gave), the saved input made from it (a source record) and the request made from that. One of each is made
    through the store and the rest are written the same way in bulk inserts: a hand-in each would take minutes."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with store.transaction(notify=False) as tx:
        watch = "scale-inbox"
        made = {
            "source": tx.create(
                "source",
                {
                    "received_at": start,
                    "kind": "mail",
                    "title": "Message",
                    "content_hash": "0" * 64,
                    "trust": "untrusted",
                    "watched": {"source": watch, "key": "message-0", "change": "new"},
                },
                _TEST,
            ),
            "snapshot": tx.create(
                "snapshot",
                {
                    "source": watch,
                    "key": "message-0",
                    "title": "Message",
                    "content_hash": "0" * 64,
                    "seen_at": start,
                    "message": {"sender": "someone@example.com", "received": start.isoformat()},
                },
                _TEST,
            ),
        }
        made["request"] = tx.create(
            "request",
            {"task": "extract", "origin": "input", "state": "done", "created_at": start, "source": made["source"].id},
            _TEST,
        )
        at = tx.sql("SELECT at FROM ledger WHERE record_id=? LIMIT 1", (made["request"].id,)).fetchone()["at"]
        records, entries = [], []
        for kind, sample in made.items():
            prefix, base = sample.id.split("-")[0], int(sample.id.split("-")[1])
            for number in range(count - 1):
                n = first + number + 1
                moment = (start + timedelta(minutes=n)).isoformat()
                data = {**sample.data, "id": f"{prefix}-{base + 1 + number}"}
                if kind == "request":
                    data.update(created_at=moment, source=f"SRC-{int(made['source'].id.split('-')[1]) + 1 + number}")
                elif kind == "source":
                    data.update(received_at=moment, watched={**data["watched"], "key": f"message-{n}"})
                else:
                    data.update(key=f"message-{n}", seen_at=moment, title=f"Message {n}")
                records.append((kind, data["id"], json.dumps(data, sort_keys=True)))
                entries.extend(
                    (at, "test.scale", kind, data["id"], field, json.dumps(data[field], sort_keys=True))
                    for field in sorted(k for k in sample.data if k != "id" and sample.data[k] is not None)
                )
            tx._c.execute("UPDATE sequences SET next=? WHERE kind=?", (base + count, kind))
        tx._c.executemany("INSERT INTO records(kind, id, version, deleted, data) VALUES(?, ?, 1, 0, ?)", records)
        tx._c.executemany(
            "INSERT INTO ledger(at, op, kind, record_id, version, field, after, actor, trust) "
            "VALUES(?,?,?,?,1,?,?,'pm','trusted')",
            entries,
        )


def steps(client: TestClient, work: Work, path: str) -> int:
    assert client.get(path).status_code == 200  # the first read, so nothing else is still starting up
    work.ticks = 0
    work.on = True
    try:
        assert client.get(path).status_code == 200
    finally:
        work.on = False
    return work.ticks


def test_the_main_screens_do_the_same_database_work_at_50000_messages_as_at_500(measured):
    client, work, store, _ = measured
    add_messages(store, FEW)
    few = {path: steps(client, work, path) for path in SCREENS}
    add_messages(store, MANY - FEW, first=FEW)
    for path in SCREENS:
        many = steps(client, work, path)
        assert many <= few[path] + GROWTH_CEILING, (
            f"{path}: {few[path]} units of work at {FEW} messages, {many} at {MANY}"
        )


def _request(tx, **fields):
    data = {"task": "extract", "origin": "input", "state": "done", "created_at": datetime(2026, 1, 1, tzinfo=UTC)}
    return tx.create("request", {**data, **fields}, _TEST)


def test_the_narrow_reads_answer_what_going_over_every_record_would(store):
    with store.transaction() as tx:
        _request(tx)
        _request(tx, state="queued")
        _request(tx, state="review", changeset="CS-1")
        _request(tx, intake="SRC-1")
        _request(tx, task="ask", origin="pm")
        gone = _request(tx, state="failed")
        tx.delete("request", gone.id, _TEST, read_version=gone.version)
    view = store.read()
    everything = view.list("request")
    ids = lambda found: [r.id for r in found]  # noqa: E731
    assert ids(view.requests_unfinished()) == ids(r for r in everything if r.data["state"] != "done")
    assert ids(view.requests_in_play()) == ids(
        r for r in everything if r.data["state"] != "done" or r.data["changeset"] or r.data["task"] == "ask"
    )
    for field in ("intake", "changeset"):
        assert ids(view.marked("request", field)) == ids(r for r in everything if r.data[field] is not None)
    assert ids(view.since("request", "created_at", "2026-01-01")) == ids(everything)
    assert view.since("request", "created_at", "2026-01-02") == []


def test_a_read_by_mark_is_refused_for_a_field_with_no_index_and_never_scans(store):
    from engine.storage import StoreError

    with pytest.raises(StoreError, match="no index"):
        store.read().marked("request", "note")
    with pytest.raises(StoreError, match="not a record kind"):
        store.read().since("request'; --", "created_at", "2026-01-01")
    assert store.read().find("run", {"request": None}) == []  # a lookup by nothing still answers


def test_what_changed_lists_open_work_and_recent_work_and_leaves_old_finished_work_out(measured):
    client, _, store, cfg = measured
    old = datetime.now(UTC) - timedelta(days=cfg.ui.changes_recent_days + 30)
    with store.transaction() as tx:
        finished_long_ago = _request(tx, created_at=old, note="finished long ago").id
        open_long_ago = _request(tx, created_at=old, state="needs_you", note="open long ago").id
        recent = _request(tx, created_at=datetime.now(UTC), note="recent").id
    listed = {item["id"] for item in client.get("/api/changes").json()}
    assert {open_long_ago, recent} <= listed
    assert finished_long_ago not in listed


def work_of(work: Work, fn) -> int:
    """The database work of one call, counted the same way as a screen's request."""
    work.ticks = 0
    work.on = True
    try:
        fn()
    finally:
        work.on = False
    return work.ticks


def _the_background_passes(client, store):
    """Each background pass that used to read every request, as a call: the five that look for waiting work, and the
    reading of the next request to run."""
    from engine import worker as worker_module

    worker = client.app.state.worker
    worker.queue_catch_up_learning()  # made once, before anything is counted

    def restore_cancelled():
        worker.restart_for.append(worker_module.RESTORE)
        worker._held_for_restore = True
        worker.restart_needed = worker_module.RESTART_NEEDED
        worker.restore_cancelled()

    return {
        "release_paused": lambda: worker_module.release_paused(store),
        "release_identity": lambda: worker_module.release_identity(store),
        "release_waiting": lambda: worker_module.release_waiting(store, "write"),
        "requeue_interrupted": lambda: worker_module.requeue_interrupted(store),
        "hold_queued": worker._hold_queued,
        "restore_cancelled": restore_cancelled,
        "run_pending": worker.run_pending,
    }


def test_the_background_passes_do_the_same_database_work_at_50000_messages_as_at_500(measured):
    client, work, store, _ = measured
    passes = _the_background_passes(client, store)
    add_messages(store, FEW)
    few = {name: work_of(work, fn) for name, fn in passes.items()}
    add_messages(store, MANY - FEW, first=FEW)
    for name, fn in passes.items():
        many = work_of(work, fn)
        assert many <= few[name] + GROWTH_CEILING, f"{name}: {few[name]} units of work at {FEW}, {many} at {MANY}"


def test_the_background_passes_still_act_on_the_requests_that_are_waiting(measured):
    from engine import worker as worker_module

    client, _, store, _ = measured
    with store.transaction() as tx:
        paused = _request(tx, state="queued", cause={"kind": "paused", "tier": "write"}, waiting="Paused")
        _request(tx, state="queued", cause={"kind": "identity", "account": "a"}, waiting="Sign in")
        running = _request(tx, state="running")
        _request(tx, state="needs_you", cause={"kind": "paused", "tier": "write"})
    assert worker_module.release_waiting(store, "write") == 1
    assert store.read().get("request", paused.id).data["cause"] is None
    assert worker_module.release_identity(store) == 1
    assert worker_module.requeue_interrupted(store) == ([running.id], [])
    assert store.read().get("request", running.id).data["state"] == "queued"


def test_undoing_a_change_does_the_same_database_work_at_50000_messages_as_at_500(measured):
    from engine import add_meeting
    from engine.applier import undo

    _, work, store, cfg = measured

    def one_undo(day: int) -> int:
        made = add_meeting.add_meeting(store, cfg, "Print sync", f"2026-10-{day:02d}", "15:00")
        return work_of(work, lambda: undo(store, made.changeset))

    add_messages(store, FEW)
    few = one_undo(16)
    add_messages(store, MANY - FEW, first=FEW)
    many = one_undo(17)
    assert many <= few + GROWTH_CEILING, f"undo: {few} units of work at {FEW} messages, {many} at {MANY}"
