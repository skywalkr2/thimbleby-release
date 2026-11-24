"""Setup turns the assistant on, waits for its first reading, and can't be skipped as a whole (S-0595 to S-0598,
design 7.8): the first go is given in the AI step and no run happens before it; the first reading is waited for after
Mail and calendar and is passed by when mail was left out; a skip shapes the steps after it; and the full-read question
is asked for every mail account added, never for one connected before the question existed. Names and days come from the
fixtures; the AI is the stub."""

from __future__ import annotations

from datetime import timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

from api.app import create_app
from engine import person_look, setup
from engine.ai.adapters.stub import set_responder
from engine.dispatcher import FIRST_GO
from engine.stages import approve_stage_request
from engine.watch import refresh
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_first_go import (
    NOTE,
    _answer,
    _data,
    _first_go_lines,
    _hand_in,
    _price,
    _process,
)
from tests.test_first_go import env as go_env  # noqa: F401 - the fixture
from tests.test_first_sign_in import NOW, TOKEN, make, run_look
from tests.test_walkthrough import _fresh, _steps, _view

# ---- S-0595: the first go is given in the AI step ------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    """The app on a workspace whose files ask for the first go (as a fresh install's do), with a priced account."""
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    path = ws.config_dir / "ai.yaml"
    held = yaml.safe_load(path.read_text())
    held.setdefault("budgets", {})["first_go"] = True
    path.write_text(yaml.safe_dump(held))
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    _price(cfg, 2.0)
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, app.state.worker
    set_responder(None)


def test_no_run_happens_before_the_go_and_giving_it_in_setup_starts_work_with_no_line_on_today(api):  # noqa: F811
    client, worker = api
    _answer()
    assert client.post("/api/handin", json={"note": "", "pasted": NOTE}).status_code == 200
    worker.run_pending()
    first = client.get("/api/setup").json()
    assert first["first_go_given"] is False and first["first_go_waiting"] == 1  # held: no run before the go
    assert [x["kind"] for x in client.get("/api/today/queue").json()].count("first_go") == 1
    assert client.get("/api/status").json()["ai"] is not None
    assert client.post("/api/runs/first-go").json()["started"] == 1  # the AI step's button
    worker.run_pending()
    given = client.get("/api/setup").json()
    assert given["first_go_given"] is True and given["first_go_waiting"] == 0
    # Later work is never held for a go again: Today has no first-go line.
    assert client.post("/api/handin", json={"note": "", "pasted": NOTE + " Another."}).status_code == 200
    worker.run_pending()
    assert client.get("/api/setup").json()["first_go_waiting"] == 0
    assert "first_go" not in [x["kind"] for x in client.get("/api/today/queue").json()]


def test_the_go_given_in_setup_is_kept_before_any_work_so_the_first_request_is_not_held(go_env):  # noqa: F811
    ws, cfg, store = go_env
    _answer()
    setup.give_first_go(ws)
    assert setup.first_go_given(ws, cfg) and not setup.first_go_holds(ws, cfg)
    request = _hand_in(go_env)
    _process(go_env, request)
    assert _data(go_env, request).get("waiting") != FIRST_GO and store.read().has("run")
    assert _first_go_lines(go_env) == []


# ---- S-0596 and S-0597: the wait, and what a skip changes -----------------------------------------------------------


def _found(ws, cfg, store, ai=True):
    """The setup steps, with the AI step standing as the test says (the fixture has no account to check)."""
    found = setup.steps(ws, cfg, store)
    next(s for s in found if s.id == "ai").done = ai
    return found


def test_the_wait_follows_the_first_reading_and_ends_with_the_look_at_who_the_person_writes_to(
    tmp_path, first_window_held
):
    ws, cfg, store = make(tmp_path)
    try:
        before = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
        assert (before.state, before.stage, before.sources, before.read) == ("working", "fetching", 2, 0)
        refresh(ws, store, cfg, "m", NOW)
        refresh(ws, store, cfg, "m2", NOW)
        mid = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW)
        assert (mid.state, mid.stage, mid.read) == ("working", "looking", 2)  # the look is due and not yet made
        request = person_look.queue(store, cfg, NOW)
        assert request is not None
        assert setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW).stage == "looking"
        run_look(ws, cfg, store, request)  # held for its go: the person's, on the next screen, never waited for here
        approve_stage_request(store, request, store.read().get("request", request).version)
        run_look(ws, cfg, store, request)
        end = setup.reading(ws, cfg, store, _found(ws, cfg, store), NOW + timedelta(minutes=1))
        assert end.state == "done" and end.read == 2
    finally:
        store.close()
        set_responder(None)


def test_with_mail_left_out_there_is_nothing_to_wait_for_and_people_is_by_hand_only(tmp_path):
    ws, c = _fresh(tmp_path)
    shown = _view(c)
    assert shown["reading"]["state"] == "none" and shown["reading"]["why"] == "no_mail"
    assert c.post("/api/setup/mail/skip").status_code == 200  # confirmed in the screen, then kept here
    shown = _view(c)
    assert _steps(c)["mail"]["skipped"] and not _steps(c)["mail"]["done"]
    assert (shown["reading"]["state"], shown["reading"]["why"]) == ("none", "no_mail")
    assert shown["people_by_hand"] is True
    # The walkthrough accepts the waiting screen as a place to be kept.
    assert c.post("/api/setup/walkthrough", json={"step": "reading"}).json()["step"] == "reading"


def test_with_no_ai_account_there_is_no_wait_even_with_mail_read(tmp_path):
    ws, cfg, store = make(tmp_path)
    try:
        found = _found(ws, cfg, store, ai=False)
        shown = setup.reading(ws, cfg, store, found, NOW)
        assert (shown.state, shown.why) == ("none", "no_ai")
        assert setup.people_by_hand(found)
    finally:
        store.close()


# ---- S-0597: no way past setup as a whole -------------------------------------------------------------------------


def test_a_confirmed_skip_is_settled_so_setup_is_finished_with_nothing_left_to_show(tmp_path):
    ws, c = _fresh(tmp_path)
    for step in ("workspace", "work", "ai", "mail", "backup", "people"):
        c.post(f"/api/setup/{step}/skip")
    view = _view(c)
    assert view["finished"] and view["settled"] == view["total"] == 6
    assert all(s["skipped"] for s in view["steps"] if s["counted"])


# ---- S-0598: the full-read question for every account added -------------------------------------------------------


def test_an_account_added_later_is_asked_and_one_read_before_the_question_existed_never_is(tmp_path):
    ws, cfg, store = make(tmp_path)
    store.close()
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        live = app.state.store
        refresh(ws, live, cfg, "m", NOW)  # connected in setup
        refresh(ws, live, cfg, "m2", NOW + timedelta(days=3))  # added later, from Connections
        assert [bool(s["full_read_open"]) for s in client.get("/api/watch").json()] == [True, True]
        # An account whose first read was made before the question existed has no mark, and is never asked.
        run = live.read().find("watch_run", {"source": "m2"})[0]
        from engine.storage import WriteContext

        with live.transaction() as tx:
            tx.update(
                "watch_run",
                run.id,
                {"asks_full_read": False},
                WriteContext(actor="engine", trust="trusted", op="test.before"),
                read_version=tx.get("watch_run", run.id).version,
            )
        assert [bool(s["full_read_open"]) for s in client.get("/api/watch").json()] == [True, False]
        assert client.get("/api/watch/m2/full-read").status_code in (200, 409)


def test_a_confirmed_i_will_say_later_on_the_mail_steps_account_question_is_kept_until_reopened(api):  # noqa: F811
    client, _worker = api
    assert client.get("/api/setup").json()["sides_later"] is False
    assert client.post("/api/setup/mail_sides/skip").status_code == 200
    assert client.get("/api/setup").json()["sides_later"] is True, (
        "kept with the setup's other answers, not in the screen"
    )
    assert client.post("/api/setup/mail_sides/reopen").status_code == 200
    assert client.get("/api/setup").json()["sides_later"] is False
