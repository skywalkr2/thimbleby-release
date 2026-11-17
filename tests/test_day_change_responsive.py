"""The app keeps answering at the day change: while the worker does its once-a-day work (the series roll, the look at
the person, the week ahead's due check), the screens' reads are not held (S-0583). The clock moves across midnight
inside this process with time-machine."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import pytest
import time_machine
from fastapi.testclient import TestClient

from api.app import create_app
from engine.today import zone
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

TOKEN = "day-change-token"
READS = ("today/priorities", "schedule", "status")
#: The most a read may take while the day-change work runs.
LIMIT_SECONDS = 1.0


@pytest.fixture
def api(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/"})
    here = zone(cfg)
    just_before = (datetime.now(here) + timedelta(days=1)).replace(hour=23, minute=59, second=50, microsecond=0)
    with time_machine.travel(just_before, tick=True) as clock:
        app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=True)
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            yield client, app.state.worker, clock, here


def _timed(client) -> dict[str, float]:
    found: dict[str, float] = {}
    for path in READS:
        began = time.perf_counter()
        answer = client.get(f"/api/{path}")
        found[path] = time.perf_counter() - began
        assert answer.status_code == 200, path
    return found


def test_screens_answer_within_a_second_while_the_day_change_work_runs(api):
    client, worker, clock, here = api
    before = _timed(client)
    day = worker.now().astimezone(here).date()
    clock.shift(timedelta(seconds=20))  # across midnight
    assert worker.now().astimezone(here).date() > day
    # The jobs loop's own pass, run on a thread of its own as the loop would, while the screens are read.
    work = threading.Thread(target=worker._jobs_pass)
    work.start()
    during = [_timed(client)]
    while work.is_alive():
        during.append(_timed(client))
    work.join()
    assert worker._rolled_on == worker.now().astimezone(here).date()  # the day-change work did run
    slowest = max(max(each.values()) for each in during)
    print(f"reads before midnight: {before}; slowest of {len(during)} rounds during the work: {slowest:.3f}s")
    assert slowest < LIMIT_SECONDS, during
