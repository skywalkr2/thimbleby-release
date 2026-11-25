"""A question to someone else links only what that person can open (design 6.8): web addresses on the public internet,
never this computer, a private network or a name that exists only inside one. Links written in the question's own text
are held to the same rule as the links it lists."""

from __future__ import annotations

import pytest

from engine.applier import Context, Inputs, _openable, check
from engine.names import People
from engine.ops import CHANGESET
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

PERSON = fixture_records(DEMO_B, "person")[1]["full_name"]
PUBLIC = "https" + "://docs.example.com/plan"
NOTICE = "Notice: the order is paused until the order is changed."


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    yield cfg, store
    store.close()


def refused(env, url=PUBLIC, text="Which date works?"):
    cfg, store = env
    op = {
        "op": "question.add",
        "to": PERSON,
        "title": "Ship now?",
        "text": text,
        "links": [{"url": url, "label": "the plan"}],
    }
    cs = CHANGESET.validate_python({"ops": [op]})
    shown = f"{NOTICE} {url} {text}"
    ctx = Context(
        store,
        cfg,
        People(store, cfg),
        ("question.add",),
        Inputs("REQ-1", None, shown, shown, "untrusted"),
        actor="assistant",
    )
    return [p.message for p in check(cs, ctx) if p.check == "question-links"]


@pytest.mark.parametrize(
    "url",
    [
        "http" + "://app.localhost/x",
        "http" + "://a.test/",
        "http" + "://192.168.1.5/",
        "http" + "://10.0.0.1:8080/",
        "http" + "://169.254.169.254/latest",
        "http" + "://[::1]/",
        "http" + "://localhost/",
        "https" + "://user@wiki.internal/page",
        "https" + "://printer.local/",
        "http" + "://127.1/",
        "http" + "://0x7f.0.0.1/",
        "http" + "://0177.0.0.1/",
        "http" + "://2130706433/",
        "http" + "://nas.home.arpa/",
        "http" + "://[fe80::1%25eth0]/",
        "http" + "://[fe80::1%eth0]/",
        "http" + "://fe80::1%eth0/",
        "http" + "://localhost.localdomain/",
        "http" + "://[::ffff:127.0.0.1]/",
        "http" + "://[fd00::5]:8080/x",
        "http" + "://1.2.3.4.5/",
        "http" + "://10.0.0.0.1/",
        "http" + "://a.b.c.0x10/",
        "http" + "://localhost6.localdomain6/",
        "http" + "://localhost4/",
        "http" + "://nas.localdomain/",
        "http" + "://printer.office.localdomain:631/",
        "http" + "://box.localhost6/",
    ],
)
def test_a_local_or_private_address_is_not_a_link_the_recipient_can_open(url):
    assert not _openable(url)


@pytest.mark.parametrize(
    "url",
    [
        PUBLIC,
        "Http" + "://docs.example.com/plan",
        "HTTPS" + "://example.com",
        "http" + "://8.8.8.8/x",
        "https" + "://a.b.example.org:8443/p?q=1",
        "https" + "://v2.example.com/",
        "https" + "://localhostess.example.com/",
        "https" + "://localhost.example.com/",
        "https" + "://10x.example.io/",
    ],
)
def test_a_public_address_is_openable(url):
    assert _openable(url)


def test_a_listed_private_link_is_refused_and_a_public_one_is_not(env):
    assert refused(env, "http" + "://10.0.0.1/doc")
    assert not refused(env)


def test_a_private_link_written_in_the_text_is_refused_though_the_listed_link_is_public(env):
    problems = refused(env, text="Details are at " + "http" + "://app.localhost/x" + ", which date works?")
    assert problems and "app.localhost" in problems[0]
    assert not refused(env, text=f"Details are at {PUBLIC}. Which date works?")


@pytest.mark.parametrize(
    "url",
    [
        "http" + "://[::1]/x",
        "http" + "://[fd00::5]/doc",
        "http" + "://0x7f.1/",
        "http" + "://[fe80::1%eth0]/doc",
        "Http" + "://localhost.localdomain/x",
    ],
)
def test_a_private_link_in_the_text_is_refused_whatever_its_shape(env, url):
    """S-0724: an IPv6 address in brackets and a browser's shorthand for loopback are found in the question's words."""
    assert refused(env, text=f"Details are at {url} and which date works?")
