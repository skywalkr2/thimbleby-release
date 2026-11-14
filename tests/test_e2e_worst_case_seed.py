"""`tests.e2e_server --worst-case` seeds the worst-case workspace a bug hunt uses (`tests/e2e_worst_case.py`): five
sides with a name of 100 characters, 50 or more to-dos of every hard kind, a week with clashes of 2, 3 and 4 meetings,
seven all-day entries on one day and an empty day, reviews waiting under more than one side, and (on the running app)
three signed-in accounts with the third refused in long words. Everything is made up."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import date, timedelta

import pytest
from starlette.testclient import TestClient

from api.app import create_app
from engine import sides
from engine.workspace import init_workspace
from tests import e2e_worst_case as worst
from tests.e2e_just_me import the_person

TOKEN = "t"


@pytest.fixture
def seeded(tmp_path):
    ws = init_workspace(tmp_path / "ws", git=False, you=the_person())
    cfg = ws.config(env={})
    app = create_app(ws, cfg, TOKEN, start_worker=False)
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
        made = worst.seed_sides(client)
        seed = worst.seed_worst_case(ws, app.state.store, cfg, made["ids"])
        yield app.state.store.read(), cfg, made, seed
    finally:
        app.state.store.close()


def test_five_sides_the_longest_named_with_100_characters(seeded):
    view, cfg, made, _ = seeded
    listed = sides.side_list(view, cfg)
    assert len(listed) == 4  # the sides added; with Personal, five
    assert cfg.workspace.project.personal not in {s.project for s in listed}
    assert max(len(n) for n in made["names"]) == 100 and all(len(n) <= 100 for n in made["names"])


def test_fifty_or_more_to_dos_of_every_hard_kind(seeded):
    view, cfg, _, seed = seeded
    me = cfg.workspace.user.person
    actions = [a.data for a in view.list("action")]
    assert len(actions) >= 50
    today = date.today()
    assert sum(1 for a in actions if a.get("due") and date.fromisoformat(str(a["due"])) < today) >= 10
    assert sum(1 for a in actions if not a.get("owners")) >= 3
    assert sum(1 for a in actions if a.get("on_hold") or a.get("told")) >= 4
    assert sum(1 for a in actions if a.get("repeat")) >= 2
    sides_with_overdue = {a.get("project") for a in actions if a.get("due") and str(a["due"]) < today.isoformat()}
    assert len(sides_with_overdue) >= 4
    texts = " ".join(a["text"] for a in actions)

    def has(low: int, high: int) -> bool:
        return any(low <= ord(c) <= high for c in texts)

    assert has(0xE0, 0xFF)  # Latin with accents
    assert has(0x400, 0x4FF)  # Cyrillic
    assert has(0x4E00, 0x9FFF) and has(0x3040, 0x30FF)  # Chinese and Japanese
    assert has(0x600, 0x6FF) and has(0x590, 0x5FF)  # Arabic and Hebrew
    assert any(a["owners"] and a["owners"][0]["person"] == me for a in actions)
    assert seed["scripts"] == 6


def test_a_week_with_clashes_of_2_3_and_4_seven_all_day_entries_and_an_empty_day(seeded):
    view, _, _, seed = seeded
    monday = date.fromisoformat(seed["week"]["monday"])
    events = [e.data for e in view.list("event")]
    timed = Counter(e["start"][:10] for e in events if "T" in e["start"])
    all_day = Counter(e["start"] for e in events if "T" not in e["start"])
    assert timed[monday.isoformat()] >= 2
    assert timed[(monday + timedelta(days=1)).isoformat()] >= 3
    assert timed[(monday + timedelta(days=2)).isoformat()] >= 4
    assert all_day[(monday + timedelta(days=2)).isoformat()] >= 6
    empty = seed["week"]["empty"]
    assert timed[empty] == 0 and all_day[empty] == 0

    def overlapping(day: int) -> int:
        spans = sorted(
            (e["start"], e["end"])
            for e in events
            if "T" in e["start"] and e["start"][:10] == (monday + timedelta(days=day)).isoformat()
        )
        return sum(1 for s in spans if s[0] < spans[0][1])

    assert [overlapping(d) for d in (0, 1, 2)] == [2, 3, 4]


def test_reviews_wait_on_today_under_more_than_one_side(seeded):
    view, _, _, seed = seeded
    held = [r for r in seed["reviews"] if r["status"] == "held"]
    assert len({r["side"] for r in held}) >= 2
    for review in held:
        action = view.get("action", review["action"]).data
        assert action["project"] == review["side"] and action.get("status", "open") == "open"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_running_app_has_three_accounts_signed_in_and_the_third_refused(tmp_path):
    port = free_port()
    # The services run on the next port; look for a pair that is free.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port + 1))
        except OSError:
            pytest.skip("the port after the app's is taken")
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.e2e_server", "--port", str(port), "--worst-case"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 120
        said: dict = {}
        while time.monotonic() < deadline:
            try:
                said = json.load(urllib.request.urlopen(f"{base}/__e2e/worst-case", timeout=5))
                if said["sign_ins"]["error"] != "not started" and (
                    said["sign_ins"]["error"] or len(said["sign_ins"]["signed_in"]) == worst.ACCOUNTS
                ):
                    break
            except OSError:
                pass
            time.sleep(0.5)
        assert said["sign_ins"]["error"] is None, said["sign_ins"]
        assert len(said["sign_ins"]["signed_in"]) == worst.ACCOUNTS
        request = urllib.request.Request(f"{base}/api/sign-ins", headers={"Authorization": "Bearer e2e-token"})
        [view] = json.load(urllib.request.urlopen(request, timeout=10))
        assert [a["status"] for a in view["accounts"]][:2] == ["signed_in", "signed_in"] and len(view["accounts"]) == 3
    finally:
        app.terminate()
        app.wait(timeout=30)
