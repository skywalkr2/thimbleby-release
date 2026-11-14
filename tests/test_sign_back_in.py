"""Signing in again is never a dead end (S-0286): the sign-in lasts a set time, and a browser with no sign-in is
given the app's own screen, which says the way back, never a bare error."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.config import ConfigError, load_config
from engine.workspace import init_workspace

TOKEN = "test-token-value"


@pytest.fixture(params=["/", "/admin"])
def built(request, tmp_path, demo):
    ws = init_workspace(tmp_path / "ws", template=demo, git=False)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><head></head><body><div id=root></div></body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    prefix = "" if request.param == "/" else request.param

    def make(**flags):
        cfg = load_config(ws.config_dir, env={}, flags={"server.base_path": request.param, **flags})
        return TestClient(create_app(ws, cfg, TOKEN, ui_dist=dist, start_worker=False)), prefix

    return make


def test_a_sign_in_lasts_the_configured_days(built):
    import json
    import time

    c, prefix = built(**{"server.cookie_max_age_days": 3})
    opened = c.post(f"{prefix}/api/session", headers={"Authorization": f"Bearer {TOKEN}"})
    assert opened.status_code == 200 and "set-cookie" not in opened.headers
    kept = json.loads(c.app.state.sessions.path.read_text())
    (ends,) = kept.values()  # the test's own pinned value is not kept on disk, so this is the one just opened
    assert abs(ends - (time.time() + 3 * 86400)) < 60


def test_the_sign_in_lifetime_has_a_default_and_a_floor(built, tmp_path):
    built()
    with pytest.raises(ConfigError):
        built(**{"server.cookie_max_age_days": 0})


def test_a_browser_without_a_sign_in_gets_the_app_screen_not_a_bare_error(built):
    c, prefix = built()
    r = c.get(f"{prefix}/", headers={"accept": "text/html"})
    assert r.status_code == 401
    assert "text/html" in r.headers["content-type"]
    assert "<div id=root>" in r.text
    # the page's files load without a sign-in, so the screen can draw; the data still needs it
    assert c.get(f"{prefix}/assets/app.js").status_code == 200
    assert c.get(f"{prefix}/api/runtime-config").status_code == 401


def test_a_wrong_link_gets_the_same_screen_and_api_calls_stay_json(built):
    c, prefix = built()
    r = c.get(f"{prefix}/?token=nope", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 401 and "text/html" in r.headers["content-type"]
    api = c.get(f"{prefix}/api/runtime-config", headers={"accept": "text/html"})
    assert api.status_code == 401 and "error" in api.json()


def test_a_file_outside_the_built_files_is_never_served_without_a_sign_in(built):
    c, prefix = built()
    assert c.get(f"{prefix}/assets/..%2f..%2fws%2fthimbleby.db").status_code != 200
    assert c.get(f"{prefix}/index.html", headers={"accept": "*/*"}).status_code == 401
