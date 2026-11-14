"""A signed catalog (design 3.11, S-0297): a feed is used only when its detached signature verifies against a key the
app trusts, or it is unsigned and the person marked it as their own. The keys are made here; none is shipped."""

import base64
from pathlib import Path

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import engine.net
from engine import catalog_signature, packs
from engine.config import ConfigError, load_config
from tests.conftest import DEMO_B

FIXTURES = Path(__file__).parent / "fixtures" / "network"
N = yaml.safe_load((FIXTURES / "network.yaml").read_text())
FEED_TEXT = (FIXTURES / "packs.yaml").read_text()
FEED = f"https://{N['catalog_host']}/packs.yaml"


def make_key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode()


def sign(private, text: str) -> str:
    return base64.b64encode(private.sign(text.encode("utf-8"))).decode()


def serve(text: str, signature: str | None, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if str(request.url).endswith(".sig"):
            return httpx.Response(200, text=signature) if signature is not None else httpx.Response(404)
        return httpx.Response(200, text=text)

    return httpx.MockTransport(handler)


def read(tmp_path, monkeypatch, text, signature, trust, **kw):
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(text, signature))
    (feed,) = packs.read_feeds([FEED], tmp_path, 24, now=kw.pop("now", 1000.0), trust=lambda _u: trust, **kw)
    return feed


def test_a_signature_verifies_only_for_the_exact_bytes_and_a_trusted_key():
    private, key = make_key()
    _, other = make_key()
    good = sign(private, "feed")
    assert catalog_signature.verify(b"feed", good, [other, key])
    assert not catalog_signature.verify(b"feed changed", good, [key])
    assert not catalog_signature.verify(b"feed", good, [other])
    assert not catalog_signature.verify(b"feed", good, [])


@pytest.mark.parametrize("signature", ["", "not base64 !!", "AAAA", base64.b64encode(b"x" * 64).decode()])
def test_an_unreadable_signature_or_key_never_verifies_and_never_raises(signature):
    _, key = make_key()
    assert not catalog_signature.verify(b"feed", signature, [key])
    assert not catalog_signature.verify(b"feed", sign(make_key()[0], "feed"), ["junk", "", "AAAA"])
    assert not catalog_signature.is_public_key("AAAA") and catalog_signature.is_public_key(key)


def test_a_feed_signed_with_a_trusted_key_is_used(tmp_path, monkeypatch):
    private, key = make_key()
    feed = read(tmp_path, monkeypatch, FEED_TEXT, sign(private, FEED_TEXT), packs.Trust((key,)))
    assert feed.entries and feed.error is None and feed.signed and not feed.unsigned_own


def test_a_changed_feed_is_refused_and_lists_nothing(tmp_path, monkeypatch):
    private, key = make_key()
    signature = sign(private, FEED_TEXT)
    changed = FEED_TEXT.replace("harbor", "harbor-two", 1)
    assert changed != FEED_TEXT
    feed = read(tmp_path, monkeypatch, changed, signature, packs.Trust((key,)))
    assert feed.entries == [] and "signature doesn't match" in feed.error and not feed.signed
    # A feed made unsigned by the person's own mark is no way round a wrong signature.
    (tmp_path / "o").mkdir()
    own = read(tmp_path / "o", monkeypatch, changed, signature, packs.Trust((key,), own=True))
    assert own.entries == [] and "signature doesn't match" in own.error


def test_a_feed_signed_by_another_key_or_with_no_signature_is_refused(tmp_path, monkeypatch):
    private, key = make_key()
    stranger, _ = make_key()
    wrong = read(tmp_path, monkeypatch, FEED_TEXT, sign(stranger, FEED_TEXT), packs.Trust((key,)))
    assert wrong.entries == [] and "signature doesn't match" in wrong.error
    none = read(tmp_path, monkeypatch, FEED_TEXT, None, packs.Trust((key,)))
    assert none.entries == [] and "isn't signed" in none.error
    # No key at all (a build with none, the repository's state): nothing is trusted, in words.
    keyless = read(tmp_path, monkeypatch, FEED_TEXT, sign(private, FEED_TEXT), packs.Trust(()))
    assert keyless.entries == [] and "no key" in keyless.error


def test_an_unsigned_feed_the_person_marked_as_their_own_is_used_and_flagged(tmp_path, monkeypatch):
    feed = read(tmp_path, monkeypatch, FEED_TEXT, None, packs.Trust((), own=True))
    assert feed.entries and feed.unsigned_own and not feed.signed


def test_the_kept_copy_is_checked_again_each_time_it_is_used(tmp_path, monkeypatch):
    private, key = make_key()
    calls: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(FEED_TEXT, sign(private, FEED_TEXT), calls))
    (first,) = packs.read_feeds([FEED], tmp_path, 24, now=1000.0, trust=lambda _u: packs.Trust((key,)))
    assert first.entries and len(calls) == 2  # the feed and its signature
    (kept,) = packs.read_feeds([FEED], tmp_path, 24, now=2000.0, trust=lambda _u: packs.Trust((key,)))
    assert kept.entries and len(calls) == 2
    # The key is taken away: the copy on disk is no longer accepted, though nothing was read again.
    (gone,) = packs.read_feeds([FEED], tmp_path, 24, now=2000.0, trust=lambda _u: packs.Trust(()))
    assert gone.entries == [] and gone.error and len(calls) == 2


def test_a_refused_read_never_replaces_the_good_copy_kept_earlier(tmp_path, monkeypatch):
    private, key = make_key()
    trust = packs.Trust((key,))
    assert read(tmp_path, monkeypatch, FEED_TEXT, sign(private, FEED_TEXT), trust).entries
    tampered = read(
        tmp_path, monkeypatch, FEED_TEXT + "\n# changed", sign(private, FEED_TEXT), trust, refresh=True, now=5000.0
    )
    assert tampered.entries == [] and tampered.error
    # The signature file can't be reached: the copy kept earlier shows, with the reason.
    monkeypatch.setattr(engine.net, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    (offline,) = packs.read_feeds([FEED], tmp_path, 24, refresh=True, now=9000.0, trust=lambda _u: trust)
    assert offline.entries and "kept earlier" in offline.notes[0] and offline.signed


def test_the_products_own_feed_is_checked_with_the_key_its_build_ships(tmp_path):
    from engine.config import load_config as load
    from engine.workspace import init_workspace

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = load(ws.config_dir, env={})
    _, shipped = make_key()
    _, added = make_key()
    own = FEED + "?own"
    other = FEED + "?other"
    product = {"pack_catalog": FEED, "pack_catalog_key": f" {shipped} "}
    cfg.workspace.plugins.catalog.keys = [added]
    cfg.workspace.plugins.catalog.own_feeds = [own]
    trust = packs.trust_for(cfg, product)
    assert trust(FEED) == packs.Trust((shipped,), False)  # the person's keys never vouch for the product's feed
    assert trust(other) == packs.Trust((added,), False)
    assert trust(own) == packs.Trust((added,), True)
    # A build that ships no key (a source checkout) reads the product's catalog as an unsigned one, with the warning;
    # one that ships a key never does.
    assert packs.trust_for(cfg, {"pack_catalog": FEED, "pack_catalog_key": ""})(FEED) == packs.Trust((), True)


def test_a_catalog_key_that_is_not_a_key_is_refused_when_saved(tmp_path):
    from engine.workspace import init_workspace

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    with pytest.raises(ConfigError):
        load_config(ws.config_dir, env={}, flags={"workspace.plugins.catalog.keys": ["not a key"]})
    own = {"workspace.plugins.catalog.own_feeds": [FEED.replace("https", "http")]}
    with pytest.raises(ConfigError):
        load_config(ws.config_dir, env={}, flags=own)


def _client(tmp_path, monkeypatch, *, own: bool, key: str | None, transport):
    from api.app import create_app
    from engine.workspace import init_workspace

    monkeypatch.setattr(engine.net, "TRANSPORT", transport)
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    settings = yaml.safe_load((ws.config_dir / "workspace.yaml").read_text())
    catalog = settings["plugins"]["catalog"]
    catalog["shipped_feed"] = False
    catalog["feeds"] = [FEED]
    catalog["own_feeds"] = [FEED] if own else []
    catalog["keys"] = [key] if key else []
    (ws.config_dir / "workspace.yaml").write_text(yaml.safe_dump(settings))
    cfg = load_config(ws.config_dir, env={})
    c = TestClient(create_app(ws, cfg, "t", start_worker=False))
    c.headers["Authorization"] = "Bearer t"
    return c, cfg.server.base_path.rstrip("/") + "/api"


def test_the_screen_marks_each_add_on_of_an_unsigned_own_feed_and_installs_nothing_from_a_refused_one(
    tmp_path, monkeypatch
):
    c, api = _client(tmp_path, monkeypatch, own=True, key=None, transport=serve(FEED_TEXT, None))
    view = c.get(f"{api}/packs").json()
    assert view["feeds"][0]["unsigned"] is True and view["feeds"][0]["signed"] is False
    assert view["available"] and all(p["unsigned"] for p in view["available"])

    other = tmp_path / "two"
    other.mkdir()
    c, api = _client(other, monkeypatch, own=False, key=None, transport=serve(FEED_TEXT, None))
    view = c.get(f"{api}/packs").json()
    assert view["available"] == [] and "isn't signed" in view["feeds"][0]["error"]
    refused = c.post(f"{api}/packs/harbor/install")
    assert refused.status_code == 404


def test_a_signed_feed_shows_no_warning(tmp_path, monkeypatch):
    private, key = make_key()
    c, api = _client(tmp_path, monkeypatch, own=False, key=key, transport=serve(FEED_TEXT, sign(private, FEED_TEXT)))
    view = c.get(f"{api}/packs").json()
    assert view["feeds"][0]["signed"] is True and view["available"]
    assert not any(p["unsigned"] for p in view["available"])


def test_adding_a_catalog_as_ones_own_lists_it_and_marks_it_and_removing_takes_both_off(tmp_path):
    from engine.workspace import init_workspace
    from tests.test_catalog_screen import fingerprint, start

    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = load_config(ws.config_dir, env={})
    c, api = start(ws, cfg)

    def catalog():
        return yaml.safe_load((ws.config_dir / "workspace.yaml").read_text())["plugins"]["catalog"]

    added = c.post(f"{api}/packs/catalogs", json={"address": FEED, "own": True, "fingerprint": fingerprint(c, api)})
    assert added.status_code == 200, added.text
    assert catalog()["feeds"] == [FEED] and catalog()["own_feeds"] == [FEED]
    gone = c.post(f"{api}/packs/catalogs/remove", json={"address": FEED, "fingerprint": added.json()["fingerprint"]})
    assert gone.status_code == 200, gone.text
    assert catalog()["feeds"] == [] and catalog()["own_feeds"] == []
