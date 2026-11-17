"""The app notices a newer version and offers it on Today (S-0152, the check). The feed is a fake: nothing reaches a
network, and what the request carries is read from the fake."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine import update_offer
from engine.config import load_config
from engine.connectors import ConnectorError
from engine.storage import Store
from engine.today_queue import queue
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

HOST = "https" + "://releases.example.com"
ADDRESS = f"{HOST}/list"
SHA = "a" * 64
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


def release(tag, *, notes="", pre=False, installer="Thimbleby-Setup.exe", draft=False):
    return {
        "tag_name": tag,
        "prerelease": pre,
        "draft": draft,
        "published_at": "2026-11-16T10:00:00Z",
        "html_url": f"{HOST}/tag/{tag}",
        "body": notes,
        "assets": [
            {
                "name": installer,
                "browser_download_url": f"{HOST}/{tag}/{installer}",
                "digest": f"sha256:{SHA}",
            }
        ],
    }


class Feed:
    """A stand-in web client: answers with `body`, or fails with `error`, and keeps what was asked."""

    def __init__(self, body=None, error=None):
        self.body, self.error, self.asked = body, error, []

    def get(self, url, **kwargs):
        self.asked.append((url, kwargs))
        if self.error:
            raise self.error

        class Answer:
            content = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()

        return Answer()

    def close(self):
        pass


def look(tmp_path, feed, **more):
    more.setdefault("current", "0.1.0")
    return update_offer.look(tmp_path, ADDRESS, web_for=lambda _url: feed, now=NOW, system="Windows", **more)


def test_a_newer_release_is_kept_and_offered_with_at_most_five_lines_of_what_changed(tmp_path):
    notes = "\n".join(f"- change {n}" for n in range(1, 9))
    found = look(tmp_path, Feed([release("v0.2.0", notes=f"## What's new\n\n{notes}"), release("v0.1.5")]))
    assert found is not None and found.version == "0.2.0"
    assert found.notes == ["What's new", "change 1", "change 2", "change 3", "change 4"]
    assert found.page == f"{HOST}/tag/v0.2.0"
    assert update_offer.offer(tmp_path, "0.1.0") == found
    assert update_offer.offer(tmp_path, "0.2.0") is None  # once the newer version runs, there is nothing to offer


def test_nothing_newer_a_failed_look_and_a_feed_that_does_not_read_each_give_no_offer(tmp_path, caplog):
    assert look(tmp_path, Feed([release("v0.1.0"), release("v0.0.9")])) is None
    assert look(tmp_path, Feed(error=ConnectorError("offline", "no network"))) is None
    assert look(tmp_path, Feed(error=ConnectorError("outage", "down"))) is None
    assert look(tmp_path, Feed(b"<html>not json")) is None
    assert look(tmp_path, Feed({"message": "rate limited"})) is None
    assert look(tmp_path, Feed([{"tag_name": 7}, "x", None, {"version": "9", "sha256": "no"}])) is None
    assert update_offer.offer(tmp_path, "0.1.0") is None


def test_a_run_of_failed_looks_is_logged_once_and_a_good_look_starts_the_count_again(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="engine.update_offer"):
        for _ in range(3):
            look(tmp_path, Feed(error=ConnectorError("outage", "down")))
        assert len(caplog.records) == 1
        look(tmp_path, Feed([release("v0.1.0")]))
        look(tmp_path, Feed(error=ConnectorError("outage", "down")))
        assert len(caplog.records) == 2


def test_a_look_that_fails_after_a_good_one_leaves_no_offer(tmp_path):
    assert look(tmp_path, Feed([release("v0.2.0")])) is not None
    assert look(tmp_path, Feed(error=ConnectorError("outage", "down"))) is None


def test_the_request_is_the_configured_address_and_one_accept_header_and_nothing_else(tmp_path):
    feed = Feed([release("v0.2.0")])
    look(tmp_path, feed)
    assert feed.asked == [(ADDRESS, {"headers": {"Accept": update_offer.ACCEPT}})]
    assert "?" not in ADDRESS


def test_later_hides_that_version_until_a_newer_one_and_undo_shows_it_again(tmp_path):
    look(tmp_path, Feed([release("v0.2.0")]))
    update_offer.later(tmp_path, "0.2.0")
    assert update_offer.offer(tmp_path, "0.1.0") is None
    assert look(tmp_path, Feed([release("v0.2.0")])) is None  # the same version, looked at again
    found = look(tmp_path, Feed([release("v0.3.0"), release("v0.2.0")]))
    assert found is not None and found.version == "0.3.0"
    update_offer.later(tmp_path, "0.3.0")
    update_offer.later(tmp_path, "0.3.0", on=False)
    assert update_offer.offer(tmp_path, "0.1.0") is not None


def test_test_releases_follow_the_setting_and_drafts_and_other_systems_installers_never_count(tmp_path):
    feed = [release("v0.2.0a1", pre=True), release("v0.1.5", draft=True), release("v0.1.2", installer="app.dmg")]
    assert look(tmp_path, Feed(feed), include_prereleases=False) is None
    assert look(tmp_path, Feed(feed), include_prereleases=True).version == "0.2.0a1"
    assert look(tmp_path, Feed([release("v0.4.0", installer="app.dmg")])) is None  # a Mac installer, on Windows
    assert (
        update_offer.look(
            tmp_path,
            ADDRESS,
            current="0.1.0",
            web_for=lambda _u: Feed([release("v0.4.0", installer="app.dmg")]),
            now=NOW,
            system="Darwin",
        ).version
        == "0.4.0"
    )


def test_the_look_is_due_once_a_day_and_a_build_with_no_feed_looks_at_nothing(tmp_path):
    assert update_offer.due(tmp_path, NOW, 24)
    look(tmp_path, Feed([release("v0.1.0")]))
    assert not update_offer.due(tmp_path, NOW + timedelta(hours=23), 24)
    assert update_offer.due(tmp_path, NOW + timedelta(hours=24), 24)
    assert (
        update_offer.feed_address({}) is None
        and update_offer.feed_address({"release_feed": "http" + "://x.test"}) is None
    )
    assert update_offer.feed_address({"release_feed": ADDRESS}) == ADDRESS
    assert update_offer.feed_address().startswith("https" + "://")  # this build names one


# ---- Today and the routes ----------------------------------------------------------------------------------------


@pytest.fixture
def running(tmp_path, monkeypatch):
    monkeypatch.setattr(update_offer, "current_version", lambda: "0.1.0")
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    Store(ws.db_path, cfg=cfg).close()
    client = TestClient(create_app(ws, cfg, "t", start_worker=False))
    client.headers["Authorization"] = "Bearer t"
    return ws, client


def rows(ws):
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    try:
        return [x for x in queue(ws, store, cfg, NOW) if x.kind == "update"]
    finally:
        store.close()


def test_a_newer_version_is_one_row_on_today_and_later_removes_it_and_undo_brings_it_back(running):
    ws, client = running
    assert rows(ws) == []
    look(ws.private_dir, Feed([release("v0.2.0", notes="Faster start\nFewer prompts"), release("v0.1.9")]))
    [row] = rows(ws)
    assert (row.subject, row.names, row.text) == (
        "0.2.0",
        ["Faster start", "Fewer prompts"],
        f"{HOST}/tag/v0.2.0",
    )
    assert [x["subject"] for x in client.get("/api/today/queue").json() if x["kind"] == "update"] == ["0.2.0"]
    assert client.post("/api/update/0.2.0/later").json() == {"ok": "0.2.0"}
    assert rows(ws) == []
    assert client.post("/api/update/0.2.0/later/undo").status_code == 200
    assert len(rows(ws)) == 1
    assert client.post("/api/update/9.9.9/later").status_code == 404


def test_turning_the_check_off_removes_the_row_and_installing_says_it_is_not_ready_and_changes_nothing(running):
    ws, client = running
    look(ws.private_dir, Feed([release("v0.2.0")]))
    answer = client.post("/api/update/0.2.0/install")
    assert answer.status_code == 409 and "isn't ready" in answer.json()["detail"]
    assert len(rows(ws)) == 1
    (ws.config_dir / "updates.yaml").write_text("version: 1\ncheck: false\n")
    assert rows(ws) == []


def test_the_worker_looks_once_when_due_and_never_when_the_check_is_off_or_no_feed_is_named(running, monkeypatch):
    ws, client = running
    import engine.worker as worker_module

    seen = []
    monkeypatch.setattr(update_offer, "look", lambda *a, **k: seen.append((a, k)))
    worker = client.app.state.worker
    assert worker.look_for_update_if_due() is None and seen == []  # the test build names no feed
    monkeypatch.setattr(worker_module, "shipped_product", lambda *a, **k: {"release_feed": ADDRESS})
    worker.look_for_update_if_due().join()
    assert len(seen) == 1 and seen[0][0][1] == ADDRESS
