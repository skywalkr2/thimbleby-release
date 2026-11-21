"""A restart and a go work whatever the background work is doing (H5-54): Restart now gives work a configured time to
stop and then restarts anyway; a go answers at once while a long sorting runs; no write is held across an AI call."""

from __future__ import annotations

import json
import threading
import time

import pytest

from engine import source_intake
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.watch import refresh
from engine.worker import Events, Worker
from tests.test_mail_sorting import make, read, rows_of, unplaced
from tests.test_mail_sorting_pending import NOTES, worker_of
from tests.test_set_aside import NOW


class Blocking:
    """An AI account whose sorting waits until released, and that notes whether a write was open when it was asked."""

    def __init__(self, store=None):
        self.store = store
        self.release = threading.Event()
        self.asked = threading.Event()
        self.writes_open = []

    def __call__(self, task):
        if self.store is not None:
            self.writes_open.append(getattr(self.store._local, "writing", 0))
        if task.kind == "notes":
            return NOTES
        self.asked.set()
        self.release.wait(timeout=20)
        return json.dumps({"answers": [{"id": r["id"], "answer": "work"} for r in rows_of(task)]})


@pytest.fixture
def blocking():
    account = Blocking()
    set_responder(account)
    yield account
    account.release.set()
    set_responder(None)


def test_a_restart_while_work_is_blocked_completes_after_the_configured_wait(tmp_path, blocking):
    ws, cfg, store = make(tmp_path, [unplaced(n) for n in range(3)])
    try:
        cfg.steward.restart_wait_seconds = 1
        read(ws, store)
        restarted = threading.Event()
        worker = Worker(
            ws,
            store,
            cfg,
            Events(),
            router_factory=lambda: Router(cfg, store, env={}, now=lambda: NOW),
            on_restart=restarted.set,
            now=lambda: NOW,
        )
        busy = threading.Thread(target=worker.run_pending, daemon=True)
        busy.start()
        assert blocking.asked.wait(timeout=10), "the work is blocked in a call"
        started = time.monotonic()
        worker.request_restart()
        assert restarted.wait(timeout=10), "the restart starts although the work does not yield"
        assert time.monotonic() - started < 5 and worker.restarting
        blocking.release.set()
        busy.join(timeout=20)
    finally:
        store.close()


def test_a_go_answers_within_a_second_while_a_long_sorting_runs_and_no_write_is_held_across_the_call(
    tmp_path, blocking, first_window_held
):
    ws, cfg, store = make(tmp_path, [unplaced(n) for n in range(5)], first_run="intake")
    try:
        blocking.store = store
        cfg.ai.budgets.confirm_unpriced = True  # unpriced runs wait for a go, so the intake does
        refresh(ws, store, cfg, "m", NOW)
        assert source_intake.grant_go(ws, store, cfg, "m", router=None, now=NOW) == 5
        worker = worker_of(ws, cfg, store)
        busy = threading.Thread(target=worker.run_pending, daemon=True)
        busy.start()
        assert blocking.asked.wait(timeout=10), "the sorting is under way"
        started = time.monotonic()
        source_intake.grant_go(ws, store, cfg, "m", router=None, now=NOW)  # a go while the sorting is in its call
        with store.transaction() as tx:  # any other write too
            tx.create("signal", {"kind": "kept", "at": NOW.isoformat(), "refs": []}, _CTX)
        assert time.monotonic() - started < 1.0
        assert set(blocking.writes_open) == {0}, "no write transaction is open while the assistant is asked"
        blocking.release.set()
        busy.join(timeout=30)
    finally:
        store.close()


from engine.storage import WriteContext  # noqa: E402

_CTX = WriteContext(actor="engine", trust="trusted", op="test")
