"""The app notices a newer version and offers it on Today (S-0152, the check). The feed is a fake: nothing reaches a
network, and what the request carries is read from the fake. Every release the fake lists carries its list of files
signed with a key made for the test run (`tests.release_signing`), which the look and the workspace are told to
trust; the tests at the end hold what happens when the list is missing, wrongly signed or doesn't match (H5-28)."""

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
from tests import release_signing
from tests.conftest import DEMO_B
from tests.release_signing import KEY, OTHER_KEY, OTHER_PUBLIC, PUBLIC

HOST = "https" + "://releases.example.com"
ADDRESS = f"{HOST}/list"
SHA = "a" * 64
NOW = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


#: The signed lists and signatures the fake release host serves, by address.
SIGNED: dict[str, bytes] = {}
KEYS = [PUBLIC]
MANIFEST, SIGNATURE = update_offer.release_manifest.MANIFEST_NAME, update_offer.release_manifest.SIGNATURE_NAME


def release(tag, *, notes="", pre=False, installer="Thimbleby-Setup.exe", draft=False, key=KEY, lists=None, sha=SHA):
    """A release as the release host lists it. Its list of files is signed with `key` (none: the release has no list);
    `lists` names another version and files for the list than the release's own."""
    assets = []
    if key is not None:
        version, files = lists or (tag.lstrip("v"), {installer: (1234, sha)})
        content = release_signing.manifest(version, files)
        for name, body in ((MANIFEST, content), (SIGNATURE, release_signing.sign(content, key).encode() + b"\n")):
            SIGNED[f"{HOST}/{tag}/{name}"] = body
            assets.append({"name": name, "browser_download_url": f"{HOST}/{tag}/{name}"})
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
            },
            *assets,
        ],
    }


class Feed:
    """A stand-in web client: answers with `body`, or fails with `error`, and keeps what was asked."""

    def __init__(self, body=None, error=None):
        self.body, self.error, self.asked, self.fetched = body, error, [], []

    def get(self, url, **kwargs):
        self.asked.append((url, kwargs))
        if self.error:
            raise self.error

        class Answer:
            content = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()

        return Answer()

    def fetch(self, url):
        """A release's list or its signature, as the release host serves the file."""
        self.fetched.append(url)
        if url not in SIGNED:
            raise ValueError("the release host answered 404")
        return SIGNED[url]

    def close(self):
        pass


def look(tmp_path, feed, **more):
    more.setdefault("current", "0.1.0")
    more.setdefault("keys", KEYS)
    more.setdefault("system", "Windows")
    return update_offer.look(tmp_path, ADDRESS, web_for=lambda _url: feed, now=NOW, fetch=feed.fetch, **more)


def test_a_newer_release_is_kept_and_offered_with_at_most_five_lines_of_what_changed(tmp_path):
    notes = "\n".join(f"- change {n}" for n in range(1, 9))
    found = look(tmp_path, Feed([release("v0.2.0", notes=f"## What's new\n\n{notes}"), release("v0.1.5")]))
    assert found is not None and found.version == "0.2.0"
    assert found.notes == ["What's new", "change 1", "change 2", "change 3", "change 4"]
    assert found.page == f"{HOST}/tag/v0.2.0"
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) == found
    assert update_offer.offer(tmp_path, "0.2.0", KEYS) is None  # once the newer version runs, there is nothing to offer


def test_nothing_newer_a_failed_look_and_a_feed_that_does_not_read_each_give_no_offer(tmp_path, caplog):
    assert look(tmp_path, Feed([release("v0.1.0"), release("v0.0.9")])) is None
    assert look(tmp_path, Feed(error=ConnectorError("offline", "no network"))) is None
    assert look(tmp_path, Feed(error=ConnectorError("outage", "down"))) is None
    assert look(tmp_path, Feed(b"<html>not json")) is None
    assert look(tmp_path, Feed({"message": "rate limited"})) is None
    assert look(tmp_path, Feed([{"tag_name": 7}, "x", None, {"version": "9", "sha256": "no"}])) is None
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None


def test_a_run_of_failed_looks_is_logged_once_and_a_good_look_starts_the_count_again(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="engine.update_offer"):
        for _ in range(3):
            look(tmp_path, Feed(error=ConnectorError("outage", "down")))
        assert len(caplog.records) == 1
        look(tmp_path, Feed([release("v0.1.0")]))
        look(tmp_path, Feed(error=ConnectorError("outage", "down")))
        assert len(caplog.records) == 2


def test_a_look_that_fails_after_a_good_one_keeps_the_offer_until_a_good_look_says_otherwise(tmp_path):
    first = look(tmp_path, Feed([release("v0.2.0")]))
    assert first is not None
    for failing in (
        Feed(error=ConnectorError("outage", "down")),
        Feed(error=ConnectorError("offline", "no network")),
        Feed(b"<html>not json"),
        Feed({"message": "rate limited"}),
    ):
        assert look(tmp_path, failing) == first, "the row stays through a failed look"
    assert look(tmp_path, Feed([release("v0.1.0")])) is None, "a good look that lists nothing newer takes it away"


def test_the_request_is_the_configured_address_and_one_accept_header_and_nothing_else(tmp_path):
    feed = Feed([release("v0.2.0")])
    look(tmp_path, feed)
    assert feed.asked == [(ADDRESS, {"headers": {"Accept": update_offer.ACCEPT}})]
    assert "?" not in ADDRESS
    # The release's list and its signature are asked for by their addresses alone.
    assert feed.fetched == [f"{HOST}/v0.2.0/{MANIFEST}", f"{HOST}/v0.2.0/{SIGNATURE}"]


def test_later_hides_that_version_until_a_newer_one_and_undo_shows_it_again(tmp_path):
    look(tmp_path, Feed([release("v0.2.0")]))
    update_offer.later(tmp_path, "0.2.0")
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None
    assert look(tmp_path, Feed([release("v0.2.0")])) is None  # the same version, looked at again
    found = look(tmp_path, Feed([release("v0.3.0"), release("v0.2.0")]))
    assert found is not None and found.version == "0.3.0"
    update_offer.later(tmp_path, "0.3.0")
    update_offer.later(tmp_path, "0.3.0", on=False)
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is not None


def test_test_releases_follow_the_setting_and_drafts_and_other_systems_installers_never_count(tmp_path):
    feed = [release("v0.2.0a1", pre=True), release("v0.1.5", draft=True), release("v0.1.2", installer="app.dmg")]
    assert look(tmp_path, Feed(feed), include_prereleases=False) is None
    assert look(tmp_path, Feed(feed), include_prereleases=True).version == "0.2.0a1"
    assert look(tmp_path, Feed([release("v0.4.0", installer="app.dmg")])) is None  # a Mac installer, on Windows
    assert look(tmp_path, Feed([release("v0.4.0", installer="app.dmg")]), system="Darwin").version == "0.4.0"


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
    release_signing.trust(ws)
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


def test_a_copy_that_is_not_the_installed_app_has_no_install_and_the_check_off_removes_the_row(running):
    ws, client = running
    look(ws.private_dir, Feed([release("v0.2.0")]))
    assert [r.state for r in rows(ws)] == ["manual"]  # the line points to the page only
    answer = client.post("/api/update/0.2.0/install")
    assert answer.status_code == 400 and "isn't the installed app" in answer.json()["detail"]
    assert len(rows(ws)) == 1
    (ws.config_dir / "updates.yaml").write_text("version: 1\ncheck: false\n")
    assert rows(ws) == []


def test_today_and_the_routes_offer_nothing_once_the_key_that_signed_the_list_is_no_longer_trusted(running):
    """The signature is checked on every read of the offer, against the keys the settings hold at that moment."""
    ws, client = running
    look(ws.private_dir, Feed([release("v0.2.0")]))
    assert len(rows(ws)) == 1
    release_signing.trust(ws, OTHER_PUBLIC)
    assert rows(ws) == []
    assert client.post("/api/update/0.2.0/install").status_code == 404
    assert client.post("/api/update/0.2.0/later").status_code == 404
    release_signing.trust(ws, OTHER_PUBLIC, PUBLIC)
    assert len(rows(ws)) == 1


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


def test_the_installed_app_starts_the_update_from_the_click_and_its_row_offers_the_install(tmp_path, monkeypatch):
    from engine import app_update

    monkeypatch.setattr(update_offer, "current_version", lambda: "0.1.0")
    monkeypatch.setattr(app_update, "own_install", lambda: app_update.Install("Darwin", tmp_path, tmp_path))
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    release_signing.trust(ws)
    cfg = ws.config(env={})
    Store(ws.db_path, cfg=cfg).close()
    asked = []
    client = TestClient(create_app(ws, cfg, "t", start_worker=False, on_update=asked.append))
    client.headers["Authorization"] = "Bearer t"
    look(ws.private_dir, Feed([release("v0.2.0")]))
    assert [r.state for r in rows(ws)] == [None]
    assert client.post("/api/update/0.2.0/install").json() == {"ok": "0.2.0"} and asked == ["0.2.0"]
    assert client.post("/api/update/9.9.9/install").status_code == 404 and asked == ["0.2.0"]


def test_a_finished_update_is_one_row_until_it_is_seen_and_the_setting_names_another_feed(tmp_path, monkeypatch):
    from engine import app_update

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    ws.private_dir.mkdir(exist_ok=True)
    cfg = ws.config(env={})
    Store(ws.db_path, cfg=cfg).close()
    client = TestClient(create_app(ws, cfg, "t", start_worker=False))
    client.headers["Authorization"] = "Bearer t"
    (ws.private_dir / app_update.RESULT_FILE).write_text(
        json.dumps({"status": "ok", "version": "0.2.0", "page": f"{HOST}/tag/v0.2.0", "notes": ["Faster start"]})
    )
    [row] = [x for x in client.get("/api/today/queue").json() if x["kind"] == "updated"]
    assert (row["subject"], row["names"], row["text"]) == ("0.2.0", ["Faster start"], f"{HOST}/tag/v0.2.0")
    assert client.post("/api/update/updated/seen").json() == {"ok": "updated"}
    assert [x for x in client.get("/api/today/queue").json() if x["kind"] == "updated"] == []
    local = "http" + "://127.0.0.1:9/list"
    assert update_offer.feed_address({}, local) == local
    assert update_offer.feed_address({"release_feed": ADDRESS}, "http" + "://example.com/x") is None


def test_the_updates_settings_are_live_so_a_change_asks_for_no_restart_and_the_running_app_follows_it(running):
    from engine.worker import is_live

    assert all(
        is_live(f"updates.{key}")
        for key in ("check", "feed_address", "include_prereleases", "check_every_hours", "trusted_keys")
    )
    ws, client = running
    started_with = ws.config(env={})  # what the running app was started with
    look(ws.private_dir, Feed([release("v0.2.0")]))
    store = Store(ws.db_path, cfg=started_with)
    try:
        shown = lambda: [x for x in queue(ws, store, started_with, NOW) if x.kind == "update"]  # noqa: E731
        assert len(shown()) == 1
        (ws.config_dir / "updates.yaml").write_text("version: 1\ncheck: false\n")
        assert shown() == [], "Today follows the file as it is now, not as the app was started"
    finally:
        store.close()


# ---- a release is offered only with its signed list of files (H5-28) -------------------------------------------


def kept(tmp_path) -> dict:
    return update_offer._read(tmp_path)


def test_a_release_with_no_signed_list_is_never_offered_and_the_log_says_so_once(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="engine.update_offer"):
        for _ in range(3):
            assert look(tmp_path, Feed([release("v0.2.0", key=None)])) is None
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None and kept(tmp_path)["found"] is None
    assert [r.getMessage() for r in caplog.records] == [
        "version 0.2.0 is listed without a list of its files signed by a trusted key; it is not offered"
    ]
    assert kept(tmp_path)["failing"] is False  # the look itself worked: nothing is shown or retried sooner


def test_a_list_signed_with_a_key_the_app_does_not_trust_is_never_offered(tmp_path):
    assert look(tmp_path, Feed([release("v0.2.0", key=OTHER_KEY)])) is None
    assert look(tmp_path, Feed([release("v0.2.0")]), keys=[]) is None  # a build with no key trusts nothing
    assert look(tmp_path, Feed([release("v0.2.0")]), keys=[OTHER_PUBLIC]) is None
    assert look(tmp_path, Feed([release("v0.2.0", key=OTHER_KEY)]), keys=[PUBLIC, OTHER_PUBLIC]).version == "0.2.0"


def test_a_release_list_changed_to_name_another_installer_and_its_checksum_is_never_offered(tmp_path):
    """The review's sequence: the release feed is changed to name another file with that file's own, matching
    checksum. The signed list still states the published installer, so nothing is offered."""
    feed = [release("v0.2.0")]
    installer = feed[0]["assets"][0]
    swapped = {**installer, "digest": "sha256:" + "b" * 64}
    assert look(tmp_path, Feed([{**feed[0], "assets": [swapped, *feed[0]["assets"][1:]]}])) is None
    moved = {**installer, "name": "Other-Setup.exe", "browser_download_url": f"{HOST}/elsewhere/Other-Setup.exe"}
    assert look(tmp_path, Feed([{**feed[0], "assets": [moved, *feed[0]["assets"][1:]]}])) is None
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None
    assert look(tmp_path, Feed(feed)).version == "0.2.0"  # the feed as it was published is offered


def test_a_signed_list_of_another_version_or_without_the_installer_is_never_offered(tmp_path):
    """A list and signature that are genuine, but an earlier release's, under a newer version's name."""
    earlier = ("0.1.5", {"Thimbleby-Setup.exe": (1234, SHA)})
    assert look(tmp_path, Feed([release("v0.2.0", lists=earlier)])) is None
    without = ("0.2.0", {"Thimbleby.dmg": (1234, SHA)})
    assert look(tmp_path, Feed([release("v0.2.0", lists=without)])) is None
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None


def test_the_checksum_and_size_offered_are_the_signed_lists_and_a_kept_offer_changed_on_disk_is_dropped(tmp_path):
    found = look(tmp_path, Feed([release("v0.2.0")]))
    assert (found.sha256, found.size) == (SHA, 1234)
    state = kept(tmp_path)
    for change in (
        {"sha256": "c" * 64},
        {"download_url": f"{HOST}/elsewhere/Other-Setup.exe"},
        {"version": "0.3.0"},
        {"signature": release_signing.sign(b"something else")},
        {"manifest": state["found"]["manifest"][:-8] + "AAAAAAA="},
    ):
        update_offer._write(tmp_path, {**state, "found": {**state["found"], **change}})
        assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None, change
    update_offer._write(tmp_path, state)
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) == found


def test_an_offer_kept_before_lists_were_signed_is_not_offered(tmp_path):
    unsigned = {"version": "0.2.0", "date": "2026-11-16", "notes": [], "page": None, "sha256": SHA}
    update_offer._write(tmp_path, {"found": {**unsigned, "download_url": f"{HOST}/v0.2.0/Thimbleby-Setup.exe"}})
    assert update_offer.offer(tmp_path, "0.1.0", KEYS) is None


def test_a_list_that_cannot_be_fetched_keeps_the_offer_already_found_and_offers_nothing_new(tmp_path):
    first = look(tmp_path, Feed([release("v0.2.0")]))
    newer = release("v0.3.0")
    del SIGNED[f"{HOST}/v0.3.0/{SIGNATURE}"]  # the list is there, its signature is not
    assert look(tmp_path, Feed([newer, release("v0.2.0")])) == first


def test_the_trusted_keys_are_the_builds_own_and_the_ones_the_settings_add(running):
    ws, _client = running
    cfg = ws.config(env={})
    assert update_offer.trusted_keys(cfg.updates, {}) == [PUBLIC]
    assert update_offer.trusted_keys(cfg.updates, {"release_key": OTHER_PUBLIC}) == [OTHER_PUBLIC, PUBLIC]
    assert update_offer.trusted_keys(None, {"release_key": ""}) == []
    from engine.shipped import product

    shipped = (product().get("release_key") or "").strip()
    assert update_offer.keys_now(ws, cfg) == [*([shipped] if shipped else []), PUBLIC]  # the build's own key first
    (ws.config_dir / "updates.yaml").write_text('version: 1\ntrusted_keys: ["not a key"]\n')
    from engine.config import ConfigError, load_config

    with pytest.raises(ConfigError):
        load_config(ws.config_dir, env={})
