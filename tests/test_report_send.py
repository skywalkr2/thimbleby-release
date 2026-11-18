"""Report a problem (design 7, Help): the report goes to the configured address only through the send route, carries
exactly the person's words, reply address, version, system and the lines shown, and says why when it did not go."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

import engine.net
from api.app import create_app
from engine import report_send
from engine.reminder_content import own_address
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

TOKEN = "test-token-value"
LOCAL_FORM = "http" + "://127.0.0.1:9/api/report"
FORM = "https" + "://form.example.com/api/report"
WORDS = "The inbox stayed blank after I signed in."
LINES = "What was happening: reading a source\nStatus: 503"


def serve(status: int = 200, seen: list | None = None):
    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(status, json={"ok": status < 300})

    return httpx.MockTransport(answer)


def test_the_address_is_the_settings_then_the_builds_and_only_https_or_this_computer():
    build = {"report_to": FORM}
    assert report_send.address("", build) == build["report_to"]
    assert report_send.address(LOCAL_FORM, build) == LOCAL_FORM
    assert report_send.address("", {}) is None
    assert report_send.address("", {"report_to": None}) is None
    assert report_send.address(FORM.replace("https", "http"), {}) is None
    assert report_send.address(FORM.replace("https", "ftp"), {}) is None


def test_a_report_carries_exactly_five_parts_and_no_identifier(monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="sam@example.com", version="9.8.7", problems=LINES)
    assert done.ok is True
    ((url, body),) = seen
    assert url == LOCAL_FORM
    assert sorted(body) == ["problems", "reply_to", "system", "version", "words"]
    assert body["words"] == WORDS and body["problems"] == LINES and body["version"] == "9.8.7"
    assert body["system"] == report_send.system_text()


@pytest.mark.parametrize(
    ("status", "why"), [(429, "busy"), (503, "unavailable"), (500, "unavailable"), (400, "refused"), (403, "refused")]
)
def test_a_form_that_does_not_take_it_says_why(monkeypatch, status, why):
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(status))
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="", version="1", problems="")
    assert (done.ok, done.why) == (False, why)


def test_no_connection_says_offline(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(engine.net, "TRANSPORT", httpx.MockTransport(refuse))
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="", version="1", problems="")
    assert (done.ok, done.why) == (False, "offline")


def make_client(tmp_path, address: str):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    flags = {"storage.backups.automatic": False, **({"ui.report_to": address} if address else {})}
    cfg = ws.config(env={}, flags=flags)
    app = create_app(ws, cfg, TOKEN, ui_dist=ws.root / "no-ui")
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}), app, cfg


def test_with_no_address_the_item_is_not_offered_and_a_send_is_refused(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, _app, _cfg = make_client(tmp_path, "")
    with client:
        assert client.get("/api/runtime-config").json()["report_enabled"] is False
        assert client.get("/api/report/facts").json()["enabled"] is False
        assert client.post("/api/report/send", json={"words": WORDS}).status_code == 404
    assert seen == []


def test_the_facts_offer_the_persons_own_address_and_a_send_reaches_the_form_once(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, app, cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        assert client.get("/api/runtime-config").json()["report_enabled"] is True
        facts = client.get("/api/report/facts").json()
        with app.state.store.read_scope():
            mine = own_address(app.state.store.read(), cfg.workspace.user.person)
        assert facts["enabled"] is True and facts["reply_to"] == mine
        assert facts["system"] == report_send.system_text() and facts["version"]
        # Nothing has left before Send.
        assert seen == []
        sent = client.post(
            "/api/report/send", json={"words": f"  {WORDS} ", "reply_to": " a@example.com ", "problems": LINES}
        )
    assert sent.json() == {"ok": True, "why": None}
    ((url, body),) = seen
    assert url == LOCAL_FORM
    assert body == {
        "words": WORDS,
        "reply_to": "a@example.com",
        "version": facts["version"],
        "system": facts["system"],
        "problems": LINES,
    }


def test_a_refusal_and_empty_words_are_answered_without_sending(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(503, seen))
    client, _app, _cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        down = client.post("/api/report/send", json={"words": WORDS})
        assert down.json() == {"ok": False, "why": "unavailable"}
        assert client.post("/api/report/send", json={"words": ""}).status_code == 422
    assert len(seen) == 1
