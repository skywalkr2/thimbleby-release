"""A session is not the install token (S-0298, design 11.4): the install token is new at each start and only opens a
session; the session is sent as a bearer header and never set as a cookie, because a cookie for this computer reaches
every local web server whatever its port."""

import json

import pytest
from fastapi.testclient import TestClient

from engine.config import load_config
from engine.sessions import MAX_SESSIONS, Sessions
from engine.workspace import init_workspace
from tests.conftest import _real_create_app

TOKEN = "install-token-value"


@pytest.fixture(params=["/", "/admin"])
def app(request, tmp_path, demo):
    ws = init_workspace(tmp_path / "ws", template=demo, git=False)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><head></head><body><div id=root></div></body></html>", encoding="utf-8")
    cfg = load_config(ws.config_dir, env={}, flags={"server.base_path": request.param})
    prefix = "" if request.param == "/" else request.param

    def make():
        # The app as the product builds it: the install token is not a session.
        return TestClient(_real_create_app(ws, cfg, TOKEN, ui_dist=dist, start_worker=False)), prefix

    return make, ws, cfg


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


def test_the_install_token_alone_opens_no_route_and_a_session_opens_them(app):
    make, _, _ = app
    c, prefix = make()
    assert c.get(f"{prefix}/api/runtime-config", headers=bearer(TOKEN)).status_code == 401
    opened = c.post(f"{prefix}/api/session", headers=bearer(TOKEN))
    assert opened.status_code == 200
    session = opened.json()["session"]
    assert session != TOKEN and len(session) >= 40
    assert c.get(f"{prefix}/api/runtime-config", headers=bearer(session)).status_code == 200
    # The same session is the page's sign-in for every call that follows.
    assert c.get(f"{prefix}/api/status", headers=bearer(session)).status_code == 200


def test_a_wrong_install_token_opens_no_session(app):
    make, _, _ = app
    c, prefix = make()
    for headers in (bearer("nope"), {}, bearer("")):
        answer = c.post(f"{prefix}/api/session", headers=headers)
        assert answer.status_code == 401 and "session" not in answer.text
    assert c.get(f"{prefix}/api/runtime-config", headers=bearer("nope")).status_code == 401


def test_no_answer_ever_sets_a_cookie_and_a_cookie_signs_nothing_in(app):
    make, _, _ = app
    c, prefix = make()
    answers = [
        c.get(f"{prefix}/?token={TOKEN}", follow_redirects=False),
        c.get(f"{prefix}/?token=nope", follow_redirects=False),
        c.post(f"{prefix}/api/session", headers=bearer(TOKEN)),
        c.get(f"{prefix}/api/health"),
    ]
    session = answers[2].json()["session"]
    answers.append(c.get(f"{prefix}/api/runtime-config", headers=bearer(session)))
    assert all("set-cookie" not in a.headers for a in answers)
    # A browser that sends the session as a cookie (which another local server could receive) gets nothing.
    bare = TestClient(c.app, cookies={"cockpit_token": session, "session": session, "token": TOKEN})
    assert bare.get(f"{prefix}/api/runtime-config").status_code == 401


def test_the_apps_own_link_opens_the_page_and_a_wrong_one_does_not(app):
    make, _, _ = app
    c, prefix = make()
    page = c.get(f"{prefix}/?token={TOKEN}", headers={"accept": "text/html"}, follow_redirects=False)
    assert page.status_code == 200 and "<div id=root>" in page.text
    wrong = c.get(f"{prefix}/?token=nope", headers={"accept": "text/html"}, follow_redirects=False)
    assert wrong.status_code == 401
    # The link's token opens no data: only the session call takes it.
    assert c.get(f"{prefix}/api/runtime-config?token={TOKEN}").status_code == 401


def test_a_session_survives_a_restart_and_the_old_link_does_not(app):
    make, ws, _ = app
    first, prefix = make()
    session = first.post(f"{prefix}/api/session", headers=bearer(TOKEN)).json()["session"]
    # The next start makes a new install token and builds the app again.
    before = ws.install_token()
    fresh = ws.new_install_token()
    assert fresh != before and ws.install_token() == fresh
    assert (ws.private_dir / "token").stat().st_mode & 0o077 == 0
    again, _ = make()
    assert again.get(f"{prefix}/api/runtime-config", headers=bearer(session)).status_code == 200
    assert again.post(f"{prefix}/api/session", headers=bearer(TOKEN)).status_code == 200  # TOKEN is this build's own
    assert again.post(f"{prefix}/api/session", headers=bearer(before)).status_code == 401


def test_a_session_sent_to_another_port_is_refused(app):
    """A stolen session sent from another local server arrives with that server's own host and port."""
    make, _, cfg = app
    c, prefix = make()
    session = c.post(f"{prefix}/api/session", headers=bearer(TOKEN)).json()["session"]
    other = {**bearer(session), "Host": f"127.0.0.1:{cfg.server.port + 1}"}
    assert c.get(f"{prefix}/api/runtime-config", headers=other).status_code == 403


# ---- the sessions' own store -----------------------------------------------------------------------------------------


def test_only_a_hash_is_kept_and_a_session_ends(tmp_path):
    sessions = Sessions(tmp_path, 1)
    value = sessions.open(now=1000.0)
    assert value not in (tmp_path / "sessions.json").read_text()
    assert sessions.valid(value, now=1000.0 + 86399)
    assert not sessions.valid(value, now=1000.0 + 86401)
    assert not sessions.valid("made-up", now=1000.0) and not sessions.valid("", now=1000.0)
    again = sessions.open()
    sessions.close(again)
    assert not sessions.valid(again)


def test_a_damaged_or_foreign_file_signs_nobody_in_and_never_raises(tmp_path):
    sessions = Sessions(tmp_path, 1)
    for text in ("not json", "[]", '{"x": "soon"}', ""):
        (tmp_path / "sessions.json").write_text(text)
        assert not sessions.valid("anything")
    assert sessions.open() and len(json.loads((tmp_path / "sessions.json").read_text())) == 1


def test_the_oldest_session_ends_when_there_are_too_many(tmp_path):
    sessions = Sessions(tmp_path, 1)
    values = [sessions.open(now=1000.0 + i) for i in range(MAX_SESSIONS + 3)]
    assert [sessions.valid(v, now=2000.0) for v in values] == [False] * 3 + [True] * MAX_SESSIONS


def test_a_pinned_value_counts_for_this_run_only_and_is_never_written(tmp_path):
    sessions = Sessions(tmp_path, 1)
    sessions.pin("fixed-value")
    assert sessions.valid("fixed-value", now=10**12)
    assert not (tmp_path / "sessions.json").exists()
    assert not Sessions(tmp_path, 1).valid("fixed-value")  # a new run (a new object) knows nothing of it
    for i in range(MAX_SESSIONS + 5):
        sessions.open(now=1000.0 + i)
    assert sessions.valid("fixed-value")
